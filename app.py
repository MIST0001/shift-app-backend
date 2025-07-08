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
        return False

    # 2. 夜勤ルール
    prev_shift = shift_draft[staff.id].get(date - timedelta(days=1))
    if prev_shift == "夜" and shift_type != "明":
        return False
    
    two_days_ago_shift = shift_draft[staff.id].get(date - timedelta(days=2))
    if two_days_ago_shift == "夜" and shift_type != "休":
        return False

    if shift_type == "夜":
        if staff.employment_type not in ["正規職員", "嘱託職員"]:
            return False

    # 3. 連勤チェック
    if shift_type in ["早", "日1", "日2", "中", "遅", "夜"] and shift_type != '明':
        consecutive_work = 0
        for i in range(1, 5): 
            if shift_draft[staff.id].get(date - timedelta(days=i)) in ["早", "日1", "日2", "中", "遅", "夜"] and shift_draft[staff.id].get(date - timedelta(days=i)) != '明':
                consecutive_work += 1
            else:
                break
        if consecutive_work >= 4:
            return False

    # 4. 公休数チェック
    TARGET_HOLIDAYS = 8 # あとで設定画面から変えられるようにしたいね！
    current_holidays = list(shift_draft[staff.id].values()).count("休")
    remaining_slots = num_days - len(shift_draft[staff.id])
    required_holidays = TARGET_HOLIDAYS - current_holidays
    
    if shift_type == "休" and current_holidays >= TARGET_HOLIDAYS:
        return False
    if shift_type in ["早", "日1", "日2", "中", "遅", "夜"] and remaining_slots < required_holidays:
        return False
    
    # 5. 総労働時間チェック（今回は簡単にするため省略）

    # 6. 日ごとの必要人数チェック
    if shift_type in ["早", "日1", "日2", "中", "遅", "夜"]:
        date_str = date.isoformat()
        required_count = required_staffing.get(date_str, {}).get(shift_type, 0)
        
        if required_count > 0:
            current_count = sum(1 for sid in all_staff_ids if shift_draft[sid].get(date) == shift_type)
            if current_count >= required_count:
                return False
    
    # 7. 新人の単独勤務チェック
    if staff.experience == "新人" and shift_type in ["早", "日1", "日2", "中", "遅", "夜"]:
        is_someone_else_working = any(shift_draft[sid].get(date) in ["早", "日1", "日2", "中", "遅", "夜"] for sid in all_staff_ids if sid != staff.id)
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

    base_shifts = ["早", "日1", "日2", "中", "遅", "夜", "休", "明", "有"]
    shift_scores = {shift: 0 for shift in base_shifts}
    
    # ★★★ ここからが新しいコードだよ！ ★★★
    # 日ごとの必要人数を優先するためのボーナスポイントだよ！
    date_str = date.isoformat()
    if date_str in required_staffing:
        for shift_type, required_count in required_staffing[date_str].items():
            if required_count > 0:
                # 今、そのシフトに何人入っているか数えるよ
                current_count = sum(1 for sid in all_staff_ids if shift_draft[sid].get(date) == shift_type)
                
                # もし必要人数より少なかったら、そのシフトの点数をグーンと上げるんだ！
                if current_count < required_count:
                    # 足りない人数が多ければ多いほど、もっと点数を高くするよ
                    shortage = required_count - current_count
                    shift_scores[shift_type] += 100 * shortage # 100点は大きなボーナスだね！
    # ★★★ ここまでが新しいコードだよ！ ★★★

    # 同じ点数のシフトがあったときに、順番が毎回バラバラになるようにシャッフルするよ！
    random.shuffle(base_shifts)
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
    TARGET_HOLIDAYS = data.get('targetHolidays', 8)
    required_staffing = data.get('required_staffing', {})

    if not year or not month: return jsonify({"error": "年と月の情報が必要です"}), 400
    app.logger.info(f"シフト自動作成リクエスト受信: {year}年{month}月")

    try:
        all_staff = db.session.query(Staff).options(db.joinedload(Staff.availabilities)).order_by(Staff.id).all()
        import calendar
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
            staff_member = next((s for s in all_staff if s.id == staff_id), None)
            for date_obj, shift_type in date_shifts.items():
                if date_obj.month == month and shift_type:
                    new_shifts.append(Shift(staff_id=staff_id, date=date_obj, shift_type=shift_type, staff=staff_member))
        
        db.session.bulk_save_objects(new_shifts)
        db.session.commit()
        
        # staffオブジェクトを正しく割り当て直す
        for s in new_shifts:
            s.staff_name = s.staff.name

        return jsonify({
            "message": final_message,
            "generated_shifts": [s.to_dict() for s in new_shifts]
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
        import calendar
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
