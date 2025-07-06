from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- データ部分を拡張 ---
# スタッフのマスターリストと、シフトのリストを分ける
STAFF_LIST = [
    {"id": 1, "name": "田中 太郎"},
    {"id": 2, "name": "鈴木 花子"},
    {"id": 3, "name": "佐藤 次郎"},
    {"id": 4, "name": "高橋 四郎"} # シフトがない人もリストに含める
]

# DUMMY_SHIFTS の部分を書き換える
DUMMY_SHIFTS = [
    # 各シフトに "id" と "notes" を追加
    {"id": 1, "date": "2025-07-01", "staff_name": "田中 太郎", "shift_type": "早", "notes": "申し送り事項あり"},
    {"id": 2, "date": "2025-07-01", "staff_name": "鈴木 花子", "shift_type": "日", "notes": ""},
    {"id": 3, "date": "2025-07-02", "staff_name": "田中 太郎", "shift_type": "夜", "notes": "リーダー担当"},
    {"id": 4, "date": "2025-07-03", "staff_name": "田中 太郎", "shift_type": "明", "notes": ""},
    {"id": 5, "date": "2025-07-03", "staff_name": "佐藤 次郎", "shift_type": "日", "notes": "研修日"},
    {"id": 6, "date": "2025-07-04", "staff_name": "鈴木 花子", "shift_type": "休", "notes": "有給休暇"}
]

# --- API部分を更新 ---
@app.route("/")
def index():
    return jsonify({"message": "シフト管理APIサーバー v2"})

# /api/shift-data というURLで、スタッフとシフトの両方を返すようにする
@app.route("/api/shift-data")
def get_shift_data():
    response_data = {
        "staff": STAFF_LIST,
        "shifts": DUMMY_SHIFTS
    }
    return jsonify(response_data)
