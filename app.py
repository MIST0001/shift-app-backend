# app.py の例
@app.route("/shifts") # 新しいURLを追加
def get_shifts():
    dummy_data = [
        {"date": "2025-07-01", "staff_name": "田中", "shift_type": "早"},
        {"date": "2025-07-01", "staff_name": "鈴木", "shift_type": "日"},
        {"date": "2025-07-02", "staff_name": "田中", "shift_type": "休"}
    ]
    return jsonify(dummy_data)
