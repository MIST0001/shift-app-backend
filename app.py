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
# --- シフト自動作成のヘルパー関数群 (Helper Functions) ---
# =================================================================

def is_shift_assignable(staff, target_date, shift_type, shift_draft, num_days_in_month, TARGET_HOLIDAYS):
    """
    指定されたスタッフ、日付、シフトの組み合わせで割り当て可能かチェックする。
    Trueなら割り当てOK、FalseならNG。
    """
    work_shifts = ["早", "日1", "日2", "中", "遅", "夜"]

    # ルール1: 勤務可否設定のチェック
    day_of_week = target_date.weekday()
    day_of_week_supabase = (day_of_week + 1) % 7
    is_available_by_setting = True
    for availability in staff.availabilities:
        if availability.day_of_week == day_of_week_supabase and availability.shift_type == shift_type:
            is_available_by_setting = availability.is_available
            break
    if not is_available_by_setting:
        return False

    # ルール2: 夜勤の後の「明→休」ルール
    prev_date = target_date - timedelta(days=1)
    prev_shift = shift_draft[staff.id].get(prev_date)
    if prev_shift == "夜" and shift_type != "明":
        return False
    two_days_ago_date = target_date - timedelta(days=2)
    two_days_ago_shift = shift_draft[staff.id].get(two_days_ago_date)
    if two_days_ago_shift == "夜" and shift_type != "休":
        return False

    # ルール3: 連勤制限のチェック (最大4連勤まで)
    if shift_type in work_shifts:
        consecutive_work_days = 0
        for i in range(1, 5):
            check_date = target_date - timedelta(days=i)
            shift_on_that_day = shift_draft[staff.id].get(check_date)
            if shift_on_that_day in work_shifts:
                consecutive_work_days += 1
            else:
                break
        if consecutive_work_days >= 4:
            return False
            
    # ルール4: 夜勤の資格チェック
    if shift_type == "夜":
        allowed_employment_types = ["正規職員", "嘱託職員"]
        if staff.employment_type not in allowed_employment_types:
            return False

    # ルール5: 月間公休数の上限・下限チェック
    current_holidays = list(shift_draft[staff.id].values()).count("休")
    assigned_days = len(shift_draft[staff.id])
    remaining_days = num_days_in_month - assigned_days
    
    if shift_type in work_shifts:
        if remaining_days <= (TARGET_HOLIDAYS - current_holidays):
            return False
    
    if shift_type == "休":
        if current_holidays >= TARGET_HOLIDAYS:
            return False

    return True

# 11. --- シフト自動作成API (POST) ---
@app.route("/api/shifts/generate", methods=['POST'])
def generate_shifts():
    data = request.get_json()
    year = data.get('year')
    month = data.get('month')
    TARGET_HOLIDAYS = data.get('targetHolidays', 8)

    if not year or not month:
        return jsonify({"error": "年と月の情報が必要です"}), 400

    app.logger.info(f"シフト自動作成リクエスト受信: {year}年{month}月 (目標公休: {TARGET_HOLIDAYS}日)")

    try:
        # 1. 必要なデータをDBから取得
        all_staff = Staff.query.options(
            joinedload(Staff.availabilities)
        ).order_by(Staff.id).all()
        
        num_days = calendar.monthrange(year, month)[1]
        start_date = DateObject(year, month, 1)
        end_date = DateObject(year, month, num_days)
        prev_month_end_date = start_date - timedelta(days=1)
        
        existing_shifts = Shift.query.filter(
            Shift.date.between(prev_month_end_date, end_date)
        ).all()
        
        # 2. シフト下書きを作成し、既存シフトを転記
        shift_draft = {staff.id: {} for staff in all_staff}
        for shift in existing_shifts:
            if shift.staff_id in shift_draft:
                shift_draft[shift.staff_id][shift.date] = shift.shift_type

        # 3. 自動作成ロジック
        all_dates_in_month = [start_date + timedelta(days=i) for i in range(num_days)]
        
        # --- ステージ1: 全員の必要公休数（休）を先に割り当てる ---
        required_holidays = {}
        for staff in all_staff:
            current_holidays = list(shift_draft[staff.id].values()).count("休")
            required_holidays[staff.id] = TARGET_HOLIDAYS - current_holidays
        
        for staff in all_staff:
            holidays_to_add = required_holidays.get(staff.id, 0)
            if holidays_to_add <= 0: continue
            
            for day in all_dates_in_month:
                if holidays_to_add > 0 and day not in shift_draft[staff.id]:
                    if is_shift_assignable(staff, day, "休", shift_draft, num_days, TARGET_HOLIDAYS):
                        shift_draft[staff.id][day] = "休"
                        holidays_to_add -= 1

        # --- ステージ2: 残りの空きマスに勤務シフトを割り当てる ---
        shift_types_to_assign = ["早", "日1", "日2", "中", "遅", "夜"]
        for day in all_dates_in_month:
            for staff in all_staff:
                if day not in shift_draft[staff.id]:
                    random.shuffle(shift_types_to_assign)
                    for shift_type in shift_types_to_assign:
                        if is_shift_assignable(staff, day, shift_type, shift_draft, num_days, TARGET_HOLIDAYS):
                            shift_draft[staff.id][day] = shift_type
                            break
        
        # 4. 完成した下書きをDB保存形式に変換
        new_shifts_to_create = []
        for staff_id, date_shifts in shift_draft.items():
            for date_obj, shift_type in date_shifts.items():
                if shift_type and date_obj >= start_date: 
                    new_shift = Shift(
                        staff_id=staff_id,
                        date=date_obj,
                        shift_type=shift_type
                    )
                    new_shifts_to_create.append(new_shift)

        # 5. 古いシフトを一度消して、新しいシフトで上書きする
        Shift.query.filter(
            Shift.date.between(start_date, end_date)
        ).delete(synchronize_session=False)

        db.session.bulk_save_objects(new_shifts_to_create)
        db.session.commit()

        app.logger.info(f"データベースのシフト情報を更新しました。")

        # 6. 完成したシフトをフロントエンドに返す
        return jsonify({
            "message": f"{year}年{month}月のシフト作成が完了しました！",
            "generated_shifts": [s.to_dict() for s in new_shifts_to_create]
        }), 200

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        app.logger.error(f"シフト自動作成中にエラーが発生: {e}")
        return jsonify({"error": "シフトの自動作成中に予期せぬエラーが発生しました。"}), 500
