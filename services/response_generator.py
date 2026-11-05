"""Evidence-bound booking response rendering."""
import json
import os

FIELD_LABELS = {
    "booking_status": "订单状态", "room_type": "预订房型",
    "check_in": "入住日期", "check_out": "退房日期",
    "guest_count": "入住人数", "breakfast_entitlement": "早餐权益",
    "parking_entitlement": "停车权益",
}

def _requested_fields(question):
    q = str(question or "").lower()
    fields = []
    if any(x in q for x in ("早餐", "含早")): fields.append("breakfast_entitlement")
    if any(x in q for x in ("停车", "车位")): fields.append("parking_entitlement")
    if any(x in q for x in ("入住", "哪天", "日期", "退房")):
        fields.extend(["check_in", "check_out"] if "退房" in q else ["check_in"])
    if any(x in q for x in ("房型", "房间", "床型", "大床", "双床")): fields.append("room_type")
    if any(x in q for x in ("状态", "确认了吗")): fields.append("booking_status")
    if any(x in q for x in ("几个人", "人数", "几位")): fields.append("guest_count")
    return list(dict.fromkeys(fields))

def _policy_answer(policy):
    if not policy:
        return "未找到该订单绑定的取消政策。为避免误导，请联系工作人员核实；我不会根据其他订单或公共规则推断。"
    lines = [f"该订单绑定的取消政策（版本 {policy.get('version', '未记录')}，时区 {policy.get('timezone', '未记录')}）："]
    for window in policy.get("windows") or []:
        lines.append("• " + str(window.get("label") or "政策条款未记录"))
    lines.append("以上为订单绑定政策原文摘要，不代表实时退款金额或渠道最终审核结果；当前版本不会执行取消或退款。")
    return "\n".join(lines)

def _fallback(question, result):
    booking = result.get("booking") or {}
    fields = _requested_fields(question)
    if not fields: fields = ["booking_status", "room_type", "check_in", "check_out"]
    lines = []
    for field in fields:
        value = booking.get(field)
        if value in (None, ""): value = "订单中未记录"
        lines.append(f"{FIELD_LABELS[field]}：{value}")
    return "已根据当前登录身份查询到您的订单。" + "；".join(lines) + "。"

def _llm_verbalize(question, facts):
    key, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
    if not key or not model: return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL") or None)
        response = client.chat.completions.create(model=model, temperature=0,
            messages=[
                {"role": "system", "content": "你是酒店订单查询助手。只根据给定 JSON facts 回答。不得补充或推断事实；缺失字段必须说未记录。不得声称执行操作。用简洁中文回答。"},
                {"role": "user", "content": json.dumps({"question": question, "facts": facts}, ensure_ascii=False)}
            ])
        answer = (response.choices[0].message.content or "").strip()
        return answer if answer and len(answer) <= 500 else None
    except Exception:
        return None

def generate_booking_answer(question, result, use_llm=True):
    fields = _requested_fields(question) or ["booking_status", "room_type", "check_in", "check_out"]
    booking = result.get("booking") or {}
    facts = {field: booking.get(field) for field in fields}
    facts["booking_id"] = booking.get("booking_id")
    if use_llm:
        answer = _llm_verbalize(question, facts)
        if answer: return answer
    return _fallback(question, result)
