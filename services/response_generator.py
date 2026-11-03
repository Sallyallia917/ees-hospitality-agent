"""Grounded natural-language rendering for authorized booking query results."""
import os

def _fallback(question, result):
    booking = result.get("booking") or {}
    q = (question or "").lower()
    parts = []
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
    return "".join(parts) or f'已查询到订单 {booking.get("booking_id", "")}。房型：{booking.get("room_type") or "未记录"}；入住：{booking.get("check_in") or "未记录"}；退房：{booking.get("check_out") or "未记录"}。'

def generate_booking_answer(question, result):
    fallback = _fallback(question, result)
    key, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
    if not key or not model or result.get("status") != "ok":
        return fallback
    booking = result.get("booking") or {}
    fields = {k: booking.get(k) for k in ("booking_id", "room_type", "check_in", "check_out", "breakfast_entitlement", "parking_entitlement")}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL") or None)
        response = client.chat.completions.create(
            model=model, temperature=0,
            messages=[
                {"role":"system","content":"你是住宿订单查询助手。只能使用给定的已授权订单字段回答，不得推断、补充或修改字段；字段为空时明确说订单未记录。不得输出其他客户信息、退款承诺或执行操作。只返回简洁中文答复。"},
                {"role":"user","content":f"问题：{question}\\n已授权订单字段：{fields}\\n安全兜底答复：{fallback}"}
            ]
        )
        answer = (response.choices[0].message.content or "").strip()
        return answer or fallback
    except Exception:
        return fallback
