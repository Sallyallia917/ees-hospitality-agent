"""Evidence-bound booking response rendering with an optional verbalization layer.

The BookingService result is authoritative. The LLM may only phrase supplied fields;
it cannot add facts, infer entitlements, or perform actions. Deterministic rendering
is the fallback and default when no model is configured.
"""
import json
import os

FIELD_LABELS = {
    "booking_status": "订单状态",
    "room_type": "预订房型",
    "check_in": "入住日期",
    "check_out": "退房日期",
    "guest_count": "入住人数",
    "breakfast_entitlement": "早餐权益",
    "parking_entitlement": "停车权益",
}

def _requested_fields(question):
    q = str(question or "").lower()
    fields = []
    if any(x in q for x in ("早餐", "含早")):
        fields.append("breakfast_entitlement")
    if any(x in q for x in ("停车", "车位")):
        fields.append("parking_entitlement")
    if any(x in q for x in ("入住", "哪天", "日期", "退房")):
        fields.extend(["check_in", "check_out"] if "退房" in q else ["check_in"])
    if any(x in q for x in ("房型", "房间", "床型", "大床", "双床")):
        fields.append("room_type")
    if any(x in q for x in ("状态", "确认了吗")):
        fields.append("booking_status")
    if any(x in q for x in ("几个人", "人数", "几位")):
        fields.append("guest_count")
    return list(dict.fromkeys(fields))

def _fallback(question, result):
    booking = result.get("booking") or {}
    fields = _requested_fields(question)
    if not fields:
        fields = ["booking_status", "room_type", "check_in", "check_out"]
    lines = []
    for field in fields:
        value = booking.get(field)
        if value in (None, ""):
            value = "订单中未记录"
        lines.append(f"{FIELD_LABELS[field]}：{value}")
    return "已根据当前登录身份查询到您的订单。" + "；".join(lines) + "。"

def _llm_verbalize(question, facts):
    key, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
    if not key or not model:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL") or None)
        response = client.chat.completions.create(
            model=model, temperature=0,
            messages=[
                {"role": "system", "content":
                 "你是酒店订单查询助手。只根据给定 JSON facts 回答用户问题。不得补充、推断或改写事实值；缺失字段必须明确说未记录。不得声称已执行任何操作。用简洁自然中文回答。"},
                {"role": "user", "content": json.dumps(
                    {"question": question, "facts": facts}, ensure_ascii=False)}
            ]
        )
        answer = (response.choices[0].message.content or "").strip()
        # Conservative sanity gate: reject empty/overlong generations.
        if not answer or len(answer) > 500:
            return None
        return answer
    except Exception:
        return None

def generate_booking_answer(question, result, use_llm=True):
    """Render only fields returned by the authenticated BookingService."""
    booking = result.get("booking") or {}
    fields = _requested_fields(question) or ["booking_status", "room_type", "check_in", "check_out"]
    facts = {field: booking.get(field) for field in fields}
    facts["booking_id"] = booking.get("booking_id")
    if use_llm:
        answer = _llm_verbalize(question, facts)
        if answer:
            return answer
    return _fallback(question, result)
