import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship, joinedload
from datetime import date as DateObject, timedelta
import random
import calendar

# 1. --- アプリケーションとデータベースの初期設定 ---
app = Flask(__name__)
CORS(app)

# Renderの環境変数からデータベースURLを取得
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    raise ValueError("DATABASE_URL is not set in the environment")

# SupabaseのPostgreSQLは 'postgres://' で始まることがあるが、SQLAlchemyは 'postgresql://' を要求する
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# SQLAlchemyをアプリケーションに連携
db = SQLAlchemy(app)


# 2. --- データベースモデルの定義 ---
# Pythonのクラスと、データベースのテーブルを対応させる

class Staff(db.Model):
    __tablename__ = 'staff'
    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String, nullable=False)
    gender = db.Column(db.String)
    employment_type = db.Column(db.String)
    experience = db.Column(db.String) # 経験列
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    # 関連付け
    shifts = relationship("Shift", back_populates="staff", cascade="all, delete-orphan")
    availabilities = relationship("StaffAvailability", back_populates="staff", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'gender': self.gender,
            'employment_type': self.employment_type,
            'experience': self.experience,
            'availabilities': [a.to_dict() for a in self.availabilities]
        }

class Shift(db.Model):
    __tablename__ = 'shifts'
    id = db.Column(db.BigInteger, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    shift_type = db.Column(db.String, nullable=False)
    notes = db.Column(db.String)
    staff_id = db.Column(db.BigInteger, db.ForeignKey('staff.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    
    staff = relationship("Staff", back_populates="shifts")

    def to_dict(self):
        data = {
            'id': self.id,
            'date': self.date.isoformat(),
            'shift_type': self.shift_type,
            'notes': self.notes,
            'staff_id': self.staff_id,
        }
        # staffオブジェクトがロードされている場合のみ名前を追加
        if self.staff:
            data['staff_name'] = self.staff.name
        return data

class StaffAvailability(db.Model):
    __tablename__ = 'staff_availability'
    id = db.Column(db.BigInteger, primary_key=True)
    staff_id = db.Column(db.BigInteger, db.ForeignKey('staff.id', ondelete='CASCADE'), nullable=False)
    day_of_week = db.Column(db.SmallInteger, nullable=False) # 0:Sun, 1:Mon...
    shift_type = db.Column(db.String, nullable=False)
    is_available = db.Column(db.Boolean, nullable=False, default=True)

    staff = relationship("Staff", back_populates="availabilities")
    
    def to_dict(self):
        return {
            'day_of_week': self.day_of_week,
            'shift_type': self.shift_type,
            'is_available': self.is_available
        }


# 3. --- APIエンドポイントの定義 ---

@app.route("/")
def index():
    try:
        staff_count = db.session.query(Staff).count()
        return jsonify({"message": f"シフト管理APIサーバー: 正常にDBに接続完了。スタッフ数: {staff_count}"})
    except Exception as e:
        app.logger.error(f"Database connection failed: {e}")
        return jsonify({"error": "データベース接続に失敗しました。"}), 500

@app.route("/api/shift-data")
def get_shift_data():
    year_str = request.args.get('year')
    month_str = request.args.get('month')

    if not year_str or not month_str:
        return jsonify({"error": "yearとmonthパラメータは必須です"}), 400

    try:
        year = int(year_str)
        month = int(month_str)

        all_staff = db.session.query(Staff).options(joinedload(Staff.availabilities)).order_by(Staff.id).all()
        
        all_shifts = db.session.query(Shift).options(joinedload(Shift.staff)).filter(
            db.extract('year', Shift.date) == year,
            db.extract('month', Shift.date) == month
        ).all()

        staff_list = [s.to_dict() for s in all_staff]
        shift_list = [s.to_dict() for s in all_shifts]
        
        response_data = {
            "staff": staff_list,
            "shifts": shift_list
        }
        return jsonify(response_data)
        
    except ValueError:
        return jsonify({"error": "yearとmonthは整数である必要があります"}), 400
    except Exception as e:
        app.logger.error(f"Failed to fetch shift data: {e}")
        return jsonify({"error": "データの取得に失敗しました。"}), 500

# 4. --- シフト追加用API (POST) ---
@app.route("/api/shifts/add", methods=['POST'])
def add_shift():
    data = request.get_json()

    if not data or not 'date' in data or not 'shift_type' in data or not 'staff_id' in data:
        return jsonify({"error": "不十分なデータです"}), 400

    try:
        new_shift = Shift(
            date=DateObject.fromisoformat(data['date']),
            shift_type=data['shift_type'],
            staff_id=data['staff_id'],
            notes=data.get('notes', '')
        )

        db.session.add(new_shift)
        db.session.commit()

        # staff情報をロードして返す
        db.session.refresh(new_shift)

        return jsonify(new_shift.to_dict()), 201

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to add shift: {e}")
        return jsonify({"error": "シフトの追加に失敗しました。"}), 500

# 5. --- シフト更新用API (PUT) ---
@app.route("/api/shifts/update/<int:shift_id>", methods=['PUT'])
def update_shift(shift_id):
    # staff情報も一緒に読み込む
    shift_to_update = db.session.query(Shift).options(joinedload(Shift.staff)).get(shift_id)

    if not shift_to_update:
        return jsonify({"error": "対象のシフトが見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "データがありません"}), 400

    try:
        shift_to_update.shift_type = data.get('shift_type', shift_to_update.shift_type)
        shift_to_update.notes = data.get('notes', shift_to_update.notes)

        db.session.commit()

        return jsonify(shift_to_update.to_dict()), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to update shift: {e}")
        return jsonify({"error": "シフトの更新に失敗しました。"}), 500

# 6. --- シフト削除用API (DELETE) ---
@app.route("/api/shifts/delete/<int:shift_id>", methods=['DELETE'])
def delete_shift(shift_id):
    shift_to_delete = db.session.query(Shift).get(shift_id)

    if not shift_to_delete:
        return jsonify({"error": "対象のシフトが見つかりません"}), 404

    try:
        db.session.delete(shift_to_delete)
        db.session.commit()

        return jsonify({"message": f"Shift with id {shift_id} has been deleted."}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to delete shift: {e}")
        return jsonify({"error": "シフトの削除に失敗しました。"}), 500

# 7. --- スタッフ追加用API (POST) ---
@app.route("/api/staff/add", methods=['POST'])
def add_staff():
    data = request.get_json()
    if not data or not 'name' in data or not data['name'].strip():
        return jsonify({"error": "スタッフ名は必須です"}), 400
    
    try:
        new_staff = Staff(
            name=data['name'],
            gender=data.get('gender'),
            employment_type=data.get('employment_type'),
            experience=data.get('experience')
        )
        db.session.add(new_staff)
        db.session.commit()
        return jsonify(new_staff.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to add staff: {e}")
        return jsonify({"error": "スタッフの追加に失敗しました。"}), 500

# 8. --- スタッフ更新用API (PUT) ---
@app.route("/api/staff/update/<int:staff_id>", methods=['PUT'])
def update_staff(staff_id):
    staff_to_update = db.session.query(Staff).get(staff_id)
    if not staff_to_update:
        return jsonify({"error": "対象のスタッフが見つかりません"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "更新データがありません"}), 400

    try:
        if 'name' in data and (not data.get('name') or not data.get('name').strip()):
             return jsonify({"error": "スタッフ名は空にできません"}), 400
        
        staff_to_update.name = data.get('name', staff_to_update.name)
        staff_to_update.gender = data.get('gender', staff_to_update.gender)
        staff_to_update.employment_type = data.get('employment_type', staff_to_update.employment_type)
        staff_to_update.experience = data.get('experience', staff_to_update.experience)

        db.session.commit()
        return jsonify(staff_to_update.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to update staff: {e}")
        return jsonify({"error": "スタッフの更新に失敗しました。"}), 500

# 9. --- スタッフ削除用API (DELETE) ---
@app.route("/api/staff/delete/<int:staff_id>", methods=['DELETE'])
def delete_staff(staff_id):
    force_delete = request.args.get('force', 'false').lower() == 'true'

    staff_to_delete = db.session.query(Staff).get(staff_id)
    if not staff_to_delete:
        return jsonify({"error": "対象のスタッフが見つかりません"}), 404
    
    # 関連するシフトがあるか確認
    if staff_to_delete.shifts:
        if not force_delete:
            # 強制削除フラグがない場合は、確認を求めるエラーを返す
            return jsonify({
                "error": "このスタッフには割り当てられたシフトがあるため、削除できません。",
                "needs_confirmation": True
            }), 400
        
        # 強制削除フラグがある場合は、関連するシフトをすべて削除
        try:
            # 関連するシフトを先に削除
            Shift.query.filter_by(staff_id=staff_id).delete(synchronize_session=False)

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Failed to delete associated shifts for staff {staff_id}: {e}")
            return jsonify({"error": "関連シフトの削除中にエラーが発生しました。"}), 500

    try:
        db.session.delete(staff_to_delete)
        db.session.commit()
        return jsonify({"message": f"Staff with id {staff_id} and all associated shifts have been deleted."}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to delete staff {staff_id}: {e}")
        return jsonify({"error": "スタッフの削除に失敗しました。"}), 500

# 10. --- スタッフ勤務可否設定更新用API (POST) ---
@app.route("/api/staff/availabilities/update/<int:staff_id>", methods=['POST'])
def update_staff_availabilities(staff_id):
    staff = db.session.query(Staff).get(staff_id)
    if not staff:
        return jsonify({"error": "スタッフが見つかりません"}), 404

    availabilities_data = request.get_json()
    
    try:
        # 既存の設定を一度すべて削除
        StaffAvailability.query.filter_by(staff_id=staff_id).delete()
        
        # 新しい設定を追加
        for av in availabilities_data:
            new_av = StaffAvailability(
                staff_id=staff_id,
                day_of_week=av['day_of_week'],
                shift_type=av['shift_type'],
                is_available=av['is_available']
            )
            db.session.add(new_av)
        
        db.session.commit()
        return jsonify({"message": "勤務可否設定を更新しました。"}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to update availabilities: {e}")
        return jsonify({"error": "設定の更新に失敗しました。"}), 500

# =================================================================
# --- ★★★ シフト自動作成 ★★★ ---
# =================================================================

def is_assignment_valid(staff, date, shift_type, shift_draft, num_days, required_staffing, all_staff_ids, TARGET_HOLIDAYS):
    """個人ルールと全体ルールのチェックをここに集約"""

    # 1. 勤務可否チェック
    day_of_week_py = date.weekday() # 0:Mon, 1:Tue ... 6:Sun
    day_of_week_db = (day_of_week_py + 1) % 7 # 0:Sun, 1:Mon ...
    # staff.availabilities から該当日の希望を探す
    is_available = True # デフォルトは勤務可
    for availability in staff.availabilities:
        if availability.day_of_week == day_of_week_db and availability.shift_type == shift_type:
            is_available = availability.is_available
            break
    if not is_available:
        return False

    # 2. 夜勤関連ルール
    prev_shift = shift_draft[staff.id].get(date - timedelta(days=1))

    # 「明」は前日が「夜」の場合のみ許可
    if shift_type == "明" and prev_shift != "夜":
        return False 

    if prev_shift == "夜" and shift_type not in ["明", "休"]:
        return False # 夜勤の次の日は明けか休み
    
    two_days_ago_shift = shift_draft[staff.id].get(date - timedelta(days=2))
    if two_days_ago_shift == "夜" and prev_shift == "明" and shift_type not in ["休"]:
         return False # 夜勤→明けの次の日は休み
    
    if shift_type == "夜":
        if staff.employment_type not in ["正規職員", "嘱託職員"]:
            return False # 夜勤は正規・嘱託のみ

    # 3. 連勤チェック (5連勤まで)
    # 勤務日 = 'Off', '休', '明', '有' 以外
    work_shifts = ["早", "日1", "日2", "中", "遅", "夜"]
    if shift_type in work_shifts:
        consecutive_work = 1
        for i in range(1, 5): 
            if shift_draft[staff.id].get(date - timedelta(days=i)) in work_shifts:
                consecutive_work += 1
            else:
                break
        if consecutive_work > 4:
            return False

    # 4. 公休数チェック
    current_holidays = list(shift_draft[staff.id].values()).count("休")
    # 月の残りの日数
    remaining_days = num_days - date.day + 1
    required_holidays = TARGET_HOLIDAYS - current_holidays
    
    if shift_type == "休" and current_holidays >= TARGET_HOLIDAYS:
        return False # 既に目標公休数に達していたら、もう休まない
    if shift_type != "休" and remaining_days < required_holidays:
        return False # 残り日数が必要公休数より少ない場合、必ず休みにする
    
    # 5. 日ごとの必要人数チェック
    if shift_type in work_shifts:
        date_str = date.isoformat()
        required_count = required_staffing.get(date_str, {}).get(shift_type, 0)
        
        if required_count > 0:
            current_count = sum(1 for sid in all_staff_ids if shift_draft[sid].get(date) == shift_type)
            if current_count >= required_count:
                return False # 既に必要人数を満たしていたら、そのシフトには入らない
    
    # 6. 新人の単独勤務チェック
    if staff.experience == "新人" and shift_type in work_shifts:
        # 自分以外の誰かが勤務しているか
        is_someone_else_working = any(shift_draft[sid].get(date) in work_shifts for sid in all_staff_ids if sid != staff.id)
        if not is_someone_else_working:
            return False # 他に誰もいなければ、新人は勤務できない

    return True

def solve_shift_puzzle(staff_list, dates_to_fill, shift_draft, num_days, required_staffing, TARGET_HOLIDAYS, target_avg_hours, depth=0):
    """バックトラッキングで再帰的に解を探す（最終調整版）"""
    
    if not dates_to_fill:
        return True 

    (date, staff), *remaining_dates = dates_to_fill
    all_staff_ids = list(shift_draft.keys())
    indent = "  " * depth

    print(f"{indent}---【探索開始 D:{depth}】---")
    print(f"{indent}日付: {date}, スタッフ: {staff.name}")

    # --- 割り当て候補のスコアリング ---
    base_shifts = ["早", "日1", "日2", "中", "遅", "夜", "休", "明"]
    shift_scores = {shift: 0 for shift in base_shifts}
    work_shifts = ["早", "日1", "日2", "中", "遅", "夜"]
    
    # 1. 緊急出勤ボーナス
    date_str = date.isoformat()
    if date_str in required_staffing:
        for shift_type, required_count in required_staffing[date_str].items():
            if required_count > 0 and shift_type in shift_scores:
                current_count = sum(1 for sid in all_staff_ids if shift_draft[sid].get(date) == shift_type)
                if current_count < required_count:
                    shortage = required_count - current_count
                    # 緊急度に応じてボーナスを大幅に引き上げる
                    shift_scores[shift_type] += 200 * shortage

    # 2. 勤務希望にボーナス/ペナルティ
    day_of_week_py = date.weekday()
    day_of_week_db = (day_of_week_py + 1) % 7
    for availability in staff.availabilities:
        if availability.day_of_week == day_of_week_db and availability.shift_type in shift_scores:
            if availability.is_available:
                 shift_scores[availability.shift_type] += 10
            else:
                 shift_scores[availability.shift_type] -= 1000

    # 3. 休日取得のボーナス
    current_holidays = list(shift_draft[staff.id].values()).count("休")
    if current_holidays < TARGET_HOLIDAYS:
        shift_scores['休'] += 50 
    
    # 4. 労働時間の平準化（ペナルティ方式）
    SHIFT_HOURS = {"早": 8, "日1": 8, "日2": 8, "中": 8, "遅": 8, "夜": 16, "明": 0, "休": 0}
    current_hours = sum(SHIFT_HOURS.get(st, 0) for st in shift_draft[staff.id].values())
    
    # 目標時間を超えている場合、勤務シフトにペナルティを与える
    if current_hours > target_avg_hours:
        penalty_point = (current_hours - target_avg_hours) / 8 * 10 # 8時間超過あたり10ポイントのペナルティ
        for shift_type in work_shifts:
            if shift_type in shift_scores:
                shift_scores[shift_type] -= penalty_point
    
    print(f"{indent}スコア: {shift_scores}")

    # --- 割り当て実行 ---
    random.shuffle(base_shifts)
    sorted_shifts = sorted(base_shifts, key=lambda s: shift_scores[s], reverse=True)

    for shift_type in sorted_shifts:
        if is_assignment_valid(staff, date, shift_type, shift_draft, num_days, required_staffing, all_staff_ids, TARGET_HOLIDAYS):
            shift_draft[staff.id][date] = shift_type
            print(f"{indent} -> 試行: {staff.name} に [{shift_type}] を割り当て")

            if solve_shift_puzzle(staff_list, remaining_dates, shift_draft, num_days, required_staffing, TARGET_HOLIDAYS, target_avg_hours, depth + 1):
                return True
            
            print(f"{indent} <- 失敗: [{shift_type}] を取り消し")
            del shift_draft[staff.id][date]

    print(f"{indent}!!! 行き詰まり D:{depth} - 日付: {date}, スタッフ: {staff.name} !!!")
    return False

# ▼▼▼【ここを修正】▼▼▼
def assign_night_shift_sets(shift_draft, all_staff, start_date, end_date, num_days, required_staffing, TARGET_HOLIDAYS):
    """
    【戦略的バージョン】夜勤セットの割り当てが最も困難なスタッフから優先的に、
    「夜→明→休」の3連続セットを割り当てる。
    """
    app.logger.info("フェーズ1:【戦略的】夜勤セットの事前割り当てを開始")
    
    night_shift_staff = [s for s in all_staff if s.employment_type in ["正規職員", "嘱託職員"]]
    if not night_shift_staff:
        app.logger.info("夜勤可能なスタッフがいないため、事前割り当てをスキップします。")
        return

    all_staff_ids = [s.id for s in all_staff]

    # --- 前月からの夜勤引き継ぎ処理 (これは変更なし) ---
    for staff in night_shift_staff:
        prev_day_shift = shift_draft[staff.id].get(start_date - timedelta(days=1))
        two_days_ago_shift = shift_draft[staff.id].get(start_date - timedelta(days=2))
        if prev_day_shift == "夜":
            if start_date <= end_date: shift_draft[staff.id][start_date] = "明"
            if start_date + timedelta(days=1) <= end_date: shift_draft[staff.id][start_date + timedelta(days=1)] = "休"
        elif two_days_ago_shift == "夜" and prev_day_shift == "明":
            if start_date <= end_date: shift_draft[staff.id][start_date] = "休"

    # --- 戦略的な夜勤セット割り当てループ ---
    while True:
        # --- 1. 現状で必要な総夜勤数を計算 ---
        total_required_nights = sum(d.get("夜", 0) for d in required_staffing.values())
        current_assigned_nights = sum(1 for shifts in shift_draft.values() for shift_type in shifts.values() if shift_type == "夜")
        
        if current_assigned_nights >= total_required_nights:
            app.logger.info("必要な夜勤数の割り当てが完了しました。")
            break

        # --- 2. 各スタッフの「夜勤セット配置可能リスト」を作成 ---
        staff_potential_placements = {}
        for staff in night_shift_staff:
            # このループでは、1人1夜勤セットずつ入れていくため、既に入っている人はスキップ
            if any(s == "夜" for s in shift_draft[staff.id].values()):
                 # 複数回入れるように一旦変更
                pass

            potential_dates = []
            for i in range(num_days - 2): # 月末2日は夜勤セットを開始できない
                date = start_date + timedelta(days=i)
                
                # is_assignment_validを使って、夜勤が配置可能かチェック
                if is_assignment_valid(staff, date, "夜", shift_draft, num_days, required_staffing, all_staff_ids, TARGET_HOLIDAYS) and \
                   is_assignment_valid(staff, date + timedelta(days=1), "明", shift_draft, num_days, required_staffing, all_staff_ids, TARGET_HOLIDAYS) and \
                   is_assignment_valid(staff, date + timedelta(days=2), "休", shift_draft, num_days, required_staffing, all_staff_ids, TARGET_HOLIDAYS):
                    potential_dates.append(date)
            
            if potential_dates:
                staff_potential_placements[staff.id] = potential_dates
        
        if not staff_potential_placements:
            app.logger.warning("夜勤セットを配置できるスタッフが一人も見つかりませんでした。")
            break

        # --- 3. 最も配置の選択肢が少ないスタッフを選ぶ ---
        sorted_staff_by_potential = sorted(staff_potential_placements.items(), key=lambda item: len(item[1]))
        
        target_staff_id, placable_dates = sorted_staff_by_potential[0]
        
        if not placable_dates:
             app.logger.warning(f"ID:{target_staff_id}は選択肢が0です。これ以上配置できません。")
             break

        # --- 4. 選ばれたスタッフの夜勤セットを配置 ---
        place_date = random.choice(placable_dates)
        
        target_staff_obj = next(s for s in all_staff if s.id == target_staff_id)
        shift_draft[target_staff_id][place_date] = "夜"
        if place_date + timedelta(days=1) <= end_date:
            shift_draft[target_staff_id][place_date + timedelta(days=1)] = "明"
        if place_date + timedelta(days=2) <= end_date:
            shift_draft[target_staff_id][place_date + timedelta(days=2)] = "休"
        app.logger.info(f"【最優先割当】{target_staff_obj.name} (選択肢:{len(placable_dates)}個) の {place_date.day}日から「夜→明→休」をセット")

    app.logger.info("フェーズ1:【戦略的】夜勤セットの事前割り当てが完了")
# ▲▲▲【新規関数ここまで】▲▲▲


@app.route("/api/shifts/generate", methods=['POST'])
def generate_shifts():
    
    data = request.get_json()
    year, month = data.get('year'), data.get('month')
    TARGET_HOLIDAYS = data.get('targetHolidays', 8)
    required_staffing = data.get('required_staffing', {})

    if not year or not month: return jsonify({"error": "年と月の情報が必要です"}), 400
    app.logger.info(f"シフト自動作成リクエスト受信: {year}年{month}月")

    try:
        # --- 準備 ---
        all_staff = db.session.query(Staff).options(joinedload(Staff.availabilities)).order_by(Staff.id).all()
        num_days = calendar.monthrange(year, month)[1]
        start_date, end_date = DateObject(year, month, 1), DateObject(year, month, num_days)
        
        prev_month_end = start_date - timedelta(days=1)
        existing_shifts = Shift.query.filter(Shift.date.between(prev_month_end, end_date)).all()

        shift_draft = {s.id: {} for s in all_staff}
        for shift in existing_shifts:
            if shift.staff_id in shift_draft:
                shift_draft[shift.staff_id][shift.date] = shift.shift_type
        
        # ==========================================================
        # ★★★ フェーズ1: 夜勤セットの事前割り当て ★★★
        # ==========================================================
        assign_night_shift_sets(shift_draft, all_staff, start_date, end_date, num_days, required_staffing, TARGET_HOLIDAYS)


        # ==========================================================
        # ★★★ フェーズ2: 残りマスのバックトラッキング ★★★
        # ==========================================================
        # 全体の総必要労働時間を計算
        SHIFT_HOURS = {"早": 8, "日1": 8, "日2": 8, "中": 8, "遅": 8, "夜": 16, "明": 0, "休": 0}
        total_required_hours = 0
        for date_str, shifts in required_staffing.items():
            for shift_type, count in shifts.items():
                total_required_hours += SHIFT_HOURS.get(shift_type, 0) * count

        workable_staff_count = len(all_staff)
        target_avg_hours = total_required_hours / workable_staff_count if workable_staff_count > 0 else 0
        
        app.logger.info(f"総必要労働時間: {total_required_hours}h, 平均目標: {target_avg_hours:.1f}h/人")

        # 未割り当てマスをリストアップ（事前割り当てされたマスは除外される）
        unassigned_slots = []
        all_dates_in_month = [start_date + timedelta(days=i) for i in range(num_days)]
        for date in all_dates_in_month:
            for staff in all_staff:
                if date not in shift_draft[staff.id]:
                    unassigned_slots.append((date, staff))
        
        # マスのソートロジック
        slot_metrics = {}
        all_staff_ids = list(shift_draft.keys())
        shift_types_to_check = ["早", "日1", "日2", "中", "遅", "夜", "休", "明"]
        
        for date, staff in unassigned_slots:
            option_count = 0
            for shift_type in shift_types_to_check:
                if is_assignment_valid(staff, date, shift_type, shift_draft, num_days, required_staffing, all_staff_ids, TARGET_HOLIDAYS):
                    option_count += 1

            day_impact = date.day 
            
            date_str = date.isoformat()
            required_sum = sum(required_staffing.get(date_str, {}).values())
            
            metric = (option_count, -day_impact, -required_sum)
            slot_metrics[(date, staff)] = metric
        
        sorted_unassigned_slots = sorted(unassigned_slots, key=lambda slot: slot_metrics[slot])

        app.logger.info(f"これから {len(sorted_unassigned_slots)} 個のマスを、選択肢の少ない順・重要度の高い順に埋めます。")
        
        # バックトラッキング実行
        success = solve_shift_puzzle(all_staff, sorted_unassigned_slots, shift_draft, num_days, required_staffing, TARGET_HOLIDAYS, target_avg_hours)

        # --- 結果をDBに保存 ---
        final_message = "シフトの自動作成が完了しました！"
        if not success:
            final_message = "シフトの自動作成を試みましたが、一部のルールを守れず未完成です。手動で調整してください。"
        
        Shift.query.filter(Shift.date.between(start_date, end_date)).delete(synchronize_session=False)
        
        new_shifts_to_save = []
        for staff_id, date_shifts in shift_draft.items():
            for date_obj, shift_type in date_shifts.items():
                if date_obj.month == month and shift_type:
                    new_shifts_to_save.append(Shift(staff_id=staff_id, date=date_obj, shift_type=shift_type))
        
        db.session.bulk_save_objects(new_shifts_to_save)
        db.session.commit()
        
        all_shifts_with_staff = db.session.query(Shift).options(joinedload(Shift.staff)).filter(Shift.date.between(start_date, end_date)).all()

        return jsonify({
            "message": final_message,
            "generated_shifts": [s.to_dict() for s in all_shifts_with_staff]
        }), 200

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        app.logger.error(f"シフト自動作成中にエラー: {e}")
        return jsonify({"error": "シフトの自動作成中に予期せぬエラーが発生しました。"}), 500

# 12. --- 月間シフト全削除API (POST) ---
@app.route("/api/shifts/clear", methods=['POST'])
def clear_all_shifts():
    data = request.get_json()
    year = data.get('year')
    month = data.get('month')

    if not year or not month:
        return jsonify({"error": "年と月の情報が必要です"}), 400

    try:
        start_date = DateObject(year, month, 1)
        end_date = (start_date + timedelta(days=31)).replace(day=1) - timedelta(days=1)

        deleted_count = Shift.query.filter(
            Shift.date.between(start_date, end_date)
        ).delete(synchronize_session=False)
        
        db.session.commit()
        
        app.logger.info(f"{year}年{month}月のシフトを {deleted_count} 件削除しました。")
        return jsonify({"message": f"{year}年{month}月の全シフトをクリアしました。"}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"シフトの全削除中にエラーが発生: {e}")
        return jsonify({"error": "シフトのクリア中にエラーが発生しました。"}), 500


# --- アプリケーションの実行 ---
if __name__ == '__main__':
    # RenderはGunicornなどのWSGIサーバーを使うので、この部分はローカル開発用
    app.run(debug=True, port=os.environ.get('PORT', 5001))
