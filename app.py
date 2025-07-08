import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from datetime import date as DateObject, timedelta
import random

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

# 11. --- ★★★ シフト自動生成API (POST) ★★★ ---
@app.route("/api/shifts/generate", methods=['POST'])
def generate_shifts():
    data = request.get_json()
    year = data.get('year')
    month = data.get('month')
    required_staffing = data.get('required_staffing', {}) # 日付ごとの必要人数
    shift_types = data.get('shift_types', ['A', 'B', 'C', 'Off']) # 'Off'もシフトの一種として扱う

    if not year or not month:
        return jsonify({"error": "yearとmonthは必須です"}), 400

    try:
        # --- 準備 ---
        all_staff = Staff.query.all()
        all_staff_ids = [s.id for s in all_staff]
        
        # スタッフの勤務希望を使いやすい形に変換しておく
        availabilities = {}
        for staff in all_staff:
            availabilities[staff.id] = {}
            #曜日(day_of_week)とシフトタイプ(shift_type)をキーにした辞書を作成
            for av in staff.availabilities:
                if av.day_of_week not in availabilities[staff.id]:
                    availabilities[staff.id][av.day_of_week] = {}
                availabilities[staff.id][av.day_of_week][av.shift_type] = av.is_available

        # --- シフト作成処理 ---
        shift_draft = {staff_id: {} for staff_id in all_staff_ids} # {staff_id: {date: shift_type}}
        
        start_date = DateObject(year, month, 1)
        # 月の最終日を計算
        end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

        # 1日から最終日までループ
        current_date = start_date
        while current_date <= end_date:
            # 曜日を取得 (0=月曜日, 6=日曜日 -> 1=月曜日, 0=日曜日に変換)
            day_of_week = (current_date.weekday() + 1) % 7
            
            # その日にまだシフトが割り当てられていないスタッフをシャッフルして、不公平感をなくす
            unassigned_staff_ids = list(all_staff_ids)
            random.shuffle(unassigned_staff_ids)

            for staff_id in unassigned_staff_ids:
                # --- 各スタッフの、その日の各シフトの「良さ」を点数付けする ---
                shift_scores = {st: 0 for st in shift_types}

                # 1. 勤務希望の反映
                for shift_type, score in shift_scores.items():
                    # 休み希望('Off')は勤務希望設定にはないので特別扱い
                    if shift_type == 'Off':
                        # 休み希望の日なら点数を高くする
                        if availabilities.get(staff_id, {}).get(day_of_week, {}).get(shift_type, False):
                           shift_scores[shift_type] += 50
                        continue

                    # 勤務希望があるかチェック
                    is_available = availabilities.get(staff_id, {}).get(day_of_week, {}).get(shift_type, False)
                    if is_available:
                        shift_scores[shift_type] += 10 # 勤務希望ならプラス10点
                    else:
                        shift_scores[shift_type] -= 1000 # 勤務不可なら絶対に入らないようにマイナス1000点

                # 2. 連勤ペナルティ (例: 5連勤以上は避ける)
                consecutive_work_days = 0
                for i in range(1, 6):
                    prev_date = current_date - timedelta(days=i)
                    if shift_draft[staff_id].get(prev_date, 'Off') != 'Off':
                        consecutive_work_days += 1
                    else:
                        break
                if consecutive_work_days >= 4:
                    shift_scores['Off'] += 20 * (consecutive_work_days - 3) # 休みへのボーナス

                # 3. 日ごとの必要人数を優先するためのボーナスポイント
                date_str = current_date.isoformat()
                if date_str in required_staffing:
                    for shift_type, required_count in required_staffing[date_str].items():
                        if required_count > 0:
                            # 今、そのシフトに何人入っているか数える
                            current_count = sum(1 for sid in all_staff_ids if shift_draft[sid].get(current_date) == shift_type)
                            
                            # もし必要人数より少なかったら、そのシフトの点数を上げる
                            if current_count < required_count:
                                shortage = required_count - current_count
                                if shift_type in shift_scores:
                                    shift_scores[shift_type] += 100 * shortage # 不足人数が多いほど高得点

                # --- 点数が最も高いシフトを割り当てる ---
                # ↓↓↓★ここからが修正・追加したコードだよ！★↓↓↓
                # 点数が同じ場合のランダム性を確保するため、まずリストをシャッフル！
                base_shifts = list(shift_scores.keys())
                random.shuffle(base_shifts)
                # その後で、点数順に並び替え！
                sorted_shifts = sorted(base_shifts, key=lambda s: shift_scores[s], reverse=True)

                # 有効なシフトの中から、点数が最も高いものを探して割り当てる
                assigned = False
                for shift_type in sorted_shifts:
                    # 勤務不可（スコアが極端に低い）でないことを確認する
                    if shift_scores[shift_type] > -500:
                        shift_draft[staff_id][current_date] = shift_type
                        assigned = True
                        break # 割り当てたらループを抜ける
                
                # もし割り当てられるシフトが一つもなければ、安全のために休みにする
                if not assigned:
                    shift_draft[staff_id][current_date] = 'Off'

            current_date += timedelta(days=1)

        # --- 作成したシフト下書きを、フロントエンドが使いやすい形式に変換 ---
        final_shifts = []
        for staff_id, date_shifts in shift_draft.items():
            for date, shift_type in date_shifts.items():
                if shift_type != 'Off': # 休みはシフトとして表示しない
                    final_shifts.append({
                        "id": f"draft_{staff_id}_{date.isoformat()}", # 仮のID
                        "staff_id": staff_id,
                        "date": date.isoformat(),
                        "shift_type": shift_type,
                        "notes": "自動生成"
                    })

        return jsonify({"generated_shifts": final_shifts}), 200

    except Exception as e:
        app.logger.error(f"Shift generation failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"シフトの自動生成に失敗しました: {e}"}), 500

# --- アプリケーションの実行 ---
if __name__ == '__main__':
    # RenderはGunicornなどのWSGIサーバーを使うので、この部分はローカル開発用
    app.run(debug=True, port=os.environ.get('PORT', 5001))
