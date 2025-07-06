import os
from flask import Flask, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from datetime import date as DateObject

# 1. --- アプリケーションとデータベースの初期設定 ---
app = Flask(__name__)
CORS(app)

# Renderの環境変数からデータベースURLを取得
# もし環境変数がなければ、ローカルテスト用にデフォルト値を設定（今回は不要ですが作法として）
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
    __tablename__ = 'staff' # 対応するテーブル名
    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    # StaffからShiftsへの関連付け（Staffインスタンスから.shiftsでアクセス可能に）
    shifts = relationship("Shift", back_populates="staff")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name
        }

class Shift(db.Model):
    __tablename__ = 'shifts' # 対応するテーブル名
    id = db.Column(db.BigInteger, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    shift_type = db.Column(db.String, nullable=False)
    notes = db.Column(db.String)
    staff_id = db.Column(db.BigInteger, db.ForeignKey('staff.id'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    
    # ShiftからStaffへの関連付け（Shiftインスタンスから.staffでアクセス可能に）
    staff = relationship("Staff", back_populates="shifts")

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(), # 日付オブジェクトを文字列に変換
            'shift_type': self.shift_type,
            'notes': self.notes,
            'staff_id': self.staff_id,
            'staff_name': self.staff.name if self.staff else None # 関連付けを使ってスタッフ名を取得
        }


# 3. --- APIエンドポイントの定義 ---

@app.route("/")
def index():
    # 簡単な接続テスト
    try:
        # データベースにクエリを投げて、接続できるか確認
        staff_count = db.session.query(Staff).count()
        return jsonify({"message": f"シフト管理APIサーバー: 正常にDBに接続完了。スタッフ数: {staff_count}"})
    except Exception as e:
        # エラーの詳細をログに出力（RenderのLogで確認できる）
        app.logger.error(f"Database connection failed: {e}")
        return jsonify({"error": "データベース接続に失敗しました。"}), 500


@app.route("/api/shift-data")
def get_shift_data():
    try:
        # データベースから全スタッフと全シフトを取得
        all_staff = db.session.query(Staff).order_by(Staff.id).all()
        all_shifts = db.session.query(Shift).all()

        # 取得したデータを辞書形式に変換
        staff_list = [s.to_dict() for s in all_staff]
        shift_list = [s.to_dict() for s in all_shifts]
        
        response_data = {
            "staff": staff_list,
            "shifts": shift_list
        }
        return jsonify(response_data)
    except Exception as e:
        app.logger.error(f"Failed to fetch shift data: {e}")
        return jsonify({"error": "データの取得に失敗しました。"}), 500
