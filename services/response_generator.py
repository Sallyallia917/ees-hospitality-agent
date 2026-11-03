"""Deterministic, evidence-bound rendering for authorized booking query results.

Booking answers deliberately do not call an LLM: a prompt is not an authorization
or factuality boundary. The service response is the source of truth.
"""

def _fallback(question, result):
    booking = result.get("booking") or {}
    q = (question or "").lower()
    parts = []
    if any(x in q for x in ("订单状态", "状态", "是否确认", "确认了吗")):
        parts.append(f'订单状态：{booking.get("booking_status") or "订单中未记录"}。')
    if any(x in q for x in ("房型", "房间", "床型", "大床", "双床")):
        parts.append(f'您这笔订单预订的房型是：{booking.get("room_type") or "订单中未记录房型"}。')
    if any(x in q for x in ("早餐", "含早")):
        value = booking.get("breakfast_entitlement")
        parts.append(f'早餐权益：{value if value not in (None, "") else "订单中未记录"}。')
    if any(x in q for x in ("停车", "车位")):
        value = booking.get("parking_entitlement")
        parts.append(f'停车权益：{value if value not in (None, "") else "订单中未记录"}。')
    if any(x in q for x in ("入住", "哪天", "日期", "退房")):
        parts.append(f'入住：{booking.get("check_in") or "未记录"}；退房：{booking.get("check_out") or "未记录"}。')
    return "".join(parts) or (
        f'已查询到订单 {booking.get("booking_id", "")}。'
        f'订单状态：{booking.get("booking_status") or "未记录"}；'
        f'房型：{booking.get("room_type") or "未记录"}；'
        f'入住：{booking.get("check_in") or "未记录"}；'
        f'退房：{booking.get("check_out") or "未记录"}。'
    )

def generate_booking_answer(question, result):
    """Render only fields returned by the authenticated BookingService."""
    return _fallback(question, result)
