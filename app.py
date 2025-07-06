from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
# CORSの設定はそのまま残します。これでどのサイトからでもAPIにアクセスできます。
CORS(app)

# --- ここからが新しい部分 ---

# 1. 仮のシフトデータを作成
# 本来はデータベースから取得しますが、まずはPythonのリストと辞書で作成します。
DUMMY_SHIFTS = [
    {
        "id": 1,
        "date": "2025-07-01",
        "staff_name": "田中 太郎",
        "shift_type": "早番"
    },
    {
        "id": 2,
        "date": "2025-07-01",
        "staff_name": "鈴木 花子",
        "shift_type": "日勤"
    },
    {
        "id": 3,
        "date": "2025-07-02",
        "staff_name": "田中 太郎",
        "shift_type": "夜勤"
    },
    {
        "id": 4,
        "date": "2025-07-03",
        "staff_name": "田中 太郎",
        "shift_type": "明休"
    },
    {
        "id": 5,
        "date": "2025-07-03",
        "staff_name": "佐藤 次郎",
        "shift_type": "日勤"
    }
]

# 2. トップページ（/）は簡単な案内のままにします
@app.route("/")
def index():
    return jsonify({"message": "シフト管理APIサーバー"})

# 3. 新しいAPIの「出口」を作成
# /api/shifts というURLにアクセスが来たら、シフトデータを返すようにします。
@app.route("/api/shifts")
def get_shifts():
    return jsonify(DUMMY_SHIFTS)
