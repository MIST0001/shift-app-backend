import os
import calendar
import random
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship, joinedload
from datetime import date as DateObject, timedelta

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

# =================================================================
# --- 定数定義 (Constants) ---
# =================================================================
SHIFT_HOURS = {
    "早": 8, "日1": 8, "日2": 8, "中": 8, "遅": 8, "夜": 16,
    "明": 0, "休": 0, "有": 0
}
WORK_SHIFTS = [s for s, h in SHIFT_HOURS.items() if h > 0]
TARGET_HOLIDAYS = 8 # デフォルトの目標公休数


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
    shifts = relationship("Shift", back_populates="staff")
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
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'shift_type': self.shift_type,
            'notes': self.notes,
            'staff_id': self.staff_id,
            'staff_name': self.staff.name if self.staff else None
        }

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

        all_staff = db.session.query(Staff).order_by(Staff.id).all()
        
        all_shifts = db.session.query(Shift).filter(
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

        return jsonify(new_shift.to_dict()), 201

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Failed to add shift: {e}")
        return jsonify({"error": "シフトの追加に失敗しました。"}), 500

# 5. --- シフト更新用API (PUT) ---
@app.route("/api/shifts/update/<int:shift_id>", methods=['PUT'])
def update_shift(shift_id):
    shift_to_update = db.session.query(Shift).get(shift_id)

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
    
    if staff_to_delete.shifts:
        if not force_delete:
            return jsonify({
                "error": "このスタッフには割り当てられたシフトがあるため、削除できません。",
                "needs_confirmation": True
            }), 400
        
        try:
            for shift in staff_to_delete.shifts:
                db.session.delete(shift)
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
        StaffAvailability.query.filter_by(staff_id=staff_id).delete()
        
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
# --- シフト自動作成 バックトラッキング版 ---
# =================================================================

def is_assignment_valid(staff, date, shift_type, shift_draft, num_days, required_staffing, all_staff_ids):
    """個人ルールと全体ルールのチェックをここに集約"""

    # 1. 勤務可否チェック
    day_of_week_py = date.weekday()
    day_of_week_db = (day_of_week_py + 1) % 7
    is_available = next((a.is_available for a in staff.availabilities if a.day_of_week == day_of_week_db and a.shift_type == shift_type), True)
    if not is_available:
        # print(f"DEBUG: [{staff.name}/{date.day}日/{shift_type}] -> NG (勤務不可)")
        return False

    # 2. 夜勤ルール
    prev_shift = shift_draft[staff.id].get(date - timedelta(days=1))
    if prev_shift == "夜" and shift_type != "明":
        # print(f"DEBUG: [{staff.name}/{date.day}日/{shift_type}] -> NG (夜勤明けルール違反)")
        return False
    
    two_days_ago_shift = shift_draft[staff.id].get(date - timedelta(days=2))
    if two_days_ago_shift == "夜" and shift_type != "休":
        # print(f"DEBUG: [{staff.name}/{date.day}日/{shift_type}] -> NG (夜勤翌々日ルール違反)")
        return False

    if shift_type == "夜":
        if staff.employment_type not in ["正規職員", "嘱託職員"]:
            # print(f"DEBUG: [{staff.name}/{date.day}日/{shift_type}] -> NG (夜勤資格なし)")
            return False

    # 3. 連勤チェック
    if shift_type in WORK_SHIFTS and shift_type != '明':
        consecutive_work = 0
        for i in range(1, 5): # 1日前から4日前までチェック
            if shift_draft[staff.id].get(date - timedelta(days=i)) in WORK_SHIFTS:
                consecutive_work += 1
            else:
                break
        if consecutive_work >= 4:
            # print(f"DEBUG: [{staff.name}/{date.day}日/{shift_type}] -> NG (5連勤以上になるため)")
            return False

    # 4. 公休数チェック
    current_holidays = list(shift_draft[staff.id].values()).count("休")
    remaining_slots = num_days - len(shift_draft[staff.id])
    required_holidays = TARGET_HOLIDAYS - current_holidays
    
    if shift_type == "休" and current_holidays >= TARGET_HOLIDAYS:
        # print(f"DEBUG: [{staff.name}/{date.day}日/{shift_type}] -> NG (公休数オーバー)")
        return False
    if shift_type in WORK_SHIFTS and remaining_slots < required_holidays:
        # print(f"DEBUG: [{staff.name}/{date.day}日/{shift_type}] -> NG (公休数が足りなくなるため)")
        return False
    
    # 5. 総労働時間チェック
    max_hours = (num_days / 7) * 40
    current_hours = sum(SHIFT_HOURS.get(s, 0) for s in shift_draft[staff.id].values())
    if current_hours + SHIFT_HOURS.get(shift_type, 0) > max_hours: return False

    # 6. 日ごとの必要人数チェック
    if shift_type in WORK_SHIFTS:
        date_str = date.isoformat()
        # その日のそのシフトに必要な人数を取得（設定がなければ0人）
        required_count = required_staffing.get(date_str, {}).get(shift_type, 0)
        
        # 今、そのシフトに入っている人数を数える
        current_count = sum(1 for sid in all_staff_ids if shift_draft[sid].get(date) == shift_type)
        
        # もし、今入ってる人数が必要人数以上なら、もう入れない
        if current_count >= required_count:
            # printデバッグを追加してもいいね！
            print(f"DEBUG: [{staff.name}/{date.day}日/{shift_type}] -> NG (必要人数 {required_count}人 を満たしているため)")
            return False
    
    # 7. 新人の単独勤務チェック
    if staff.experience == "新人" and shift_type in WORK_SHIFTS:
        is_someone_else_working = any(shift_draft[sid].get(date) in WORK_SHIFTS for sid in all_staff_ids if sid != staff.id)
        if not is_someone_else_working:
            return False

    return True


def solve_shift_puzzle(staff_list, dates_to_fill, shift_draft, num_days, required_staffing):
    """バックトラッキングで再帰的に解を探す（スコアリング付き）"""
    
    if not dates_to_fill:
        return True

    date, staff = dates_to_fill[0]
    remaining_dates = dates_to_fill[1:]
    all_staff_ids = shift_draft.keys()

    # --- 候補シフトの優先順位付けロジック ---
    base_shifts = ["早", "日1", "日2", "中", "遅", "夜", "休", "明", "有"]
    shift_scores = {shift: 0 for shift in base_shifts}

    # 努力目標1: 夜勤の公平性
    date_str = date.isoformat()
    required_night_shift = required_staffing.get(date_str, {}).get("夜", 0)
    if required_night_shift > 0 and sum(1 for sid in all_staff_ids if shift_draft[sid].get(date) == "夜") < required_night_shift:
        night_counts = {sid: list(d.values()).count("夜") for sid, d in shift_draft.items()}
        avg_nights = sum(night_counts.values()) / len(staff_list) if staff_list else 0
        if night_counts.get(staff.id, 0) <= avg_nights:
            shift_scores["夜"] += 10

    # 努力目標2: 入浴日の特別配置
    day_of_week = date.weekday() # 月曜0..日曜6
    day_shift_types = ["日1", "日2", "中"]
    if staff.gender == "男性":
        if day_of_week == 0: # 月曜
            for s in day_shift_types: shift_scores[s] += 5
        elif day_of_week == 1 or day_of_week == 4: # 火曜 or 金曜
            shift_scores["早"] += 5
            for s in day_shift_types: shift_scores[s] += 5
    elif staff.gender == "女性":
        if day_of_week == 0 or day_of_week == 3: # 月曜 or 木曜
             for s in day_shift_types: shift_scores[s] += 5
    
    sorted_shifts = sorted(base_shifts, key=lambda s: shift_scores[s], reverse=True)

    for shift_type in sorted_shifts:
        if is_assignment_valid(staff, date, shift_type, shift_draft, num_days, required_staffing, all_staff_ids):
            shift_draft[staff.id][date] = shift_type
            if solve_shift_puzzle(staff_list, remaining_dates, shift_draft, num_days, required_staffing):
                return True
            del shift_draft[staff.id][date]

    return False

# 11. --- シフト自動作成API (POST) ---
@app.route("/api/shifts/generate", methods=['POST'])
def generate_shifts():
    data = request.get_json()
    year, month = data.get('year'), data.get('month')
    global TARGET_HOLIDAYS
    TARGET_HOLIDAYS = data.get('targetHolidays', 8)
    required_staffing = data.get('required_staffing', {})

    if not year or not month: return jsonify({"error": "年と月の情報が必要です"}), 400
    app.logger.info(f"シフト自動作成(v5)リクエスト受信: {year}年{month}月")

    try:
        all_staff = Staff.query.options(db.joinedload(Staff.availabilities)).order_by(Staff.id).all()
        num_days = calendar.monthrange(year, month)[1]
        start_date, end_date = DateObject(year, month, 1), DateObject(year, month, num_days)
        prev_month_end = start_date - timedelta(days=1)
        existing_shifts = Shift.query.filter(Shift.date.between(prev_month_end, end_date)).all()

        shift_draft = {s.id: {} for s in all_staff}
        for shift in existing_shifts:
            if shift.staff_id in shift_draft:
                shift_draft[shift.staff_id][shift.date] = shift.shift_type
        
        unassigned_slots = []
        all_dates_in_month = [start_date + timedelta(days=i) for i in range(num_days)]
        for date in all_dates_in_month:
            for staff in all_staff:
                if date not in shift_draft[staff.id]:
                    unassigned_slots.append((date, staff))
        
        # --- 探索順の最適化 ---
        slot_options = {}
        all_staff_ids = shift_draft.keys()
        for date, staff in unassigned_slots:
            count = 0
            for shift_type in ["早", "日1", "日2", "中", "遅", "夜", "休"]:
                if is_assignment_valid(staff, date, shift_type, shift_draft, num_days, required_staffing, all_staff_ids):
                    count += 1
            slot_options[(date, staff)] = count
        
        sorted_unassigned_slots = sorted(unassigned_slots, key=lambda slot: slot_options[slot])

        app.logger.info(f"これから {len(sorted_unassigned_slots)} 個のマスを、選択肢の少ない順に埋めます。")
        
        success = solve_shift_puzzle(all_staff, sorted_unassigned_slots, shift_draft, num_days, required_staffing)

        final_message = "シフトの自動作成が完了しました！"
        if not success:
            final_message = "シフトの自動作成を試みましたが、一部のルールを守れず未完成です。手動で調整してください。"
        
        Shift.query.filter(Shift.date.between(start_date, end_date)).delete(synchronize_session=False)
        
        new_shifts = []
        for staff_id, date_shifts in shift_draft.items():
            for date_obj, shift_type in date_shifts.items():
                if date_obj.month == month and shift_type:
                    new_shifts.append(Shift(staff_id=staff_id, date=date_obj, shift_type=shift_type, staff=next((s for s in all_staff if s.id == staff_id), None)))
        
        db.session.bulk_save_objects(new_shifts)
        db.session.commit()
        
        return jsonify({
            "message": final_message,
            "generated_shifts": [s.to_dict() for s in new_shifts]
        }), 200

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
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
        num_days = calendar.monthrange(year, month)[1]
        start_date = DateObject(year, month, 1)
        end_date = DateObject(year, month, num_days)

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
