"""Hybrid intent classification: deterministic rules first, optional LLM for ambiguity.
LLM output is advisory only; authorization and routing remain deterministic.
"""
import json
import os

INTENTS = {
    "public_knowledge_inquiry", "booking_related_inquiry", "realtime_availability",
    "transaction_request", "service_request", "complaint", "safety_incident", "ambiguous"
}

def _normalize(text):
    return "".join(str(text or "").lower().split()).replace("？", "?")

def classify_by_rules(query, history=None):
    text = _normalize(query)
    history = history or []
    # Explicit negation of booking must not be interpreted as an existing booking.
    no_booking = any(x in text for x in ("还没预订", "还没有预订", "没有预订", "尚未预订", "没下单", "未下单"))
    safety = ("燃气", "煤气", "起火", "冒火花", "电线冒烟", "漏电", "有人受伤", "火灾")
    if any(x in text for x in safety):
        return {"intent":"safety_incident","sub_intent":"safety","entities":{},"confidence":1.0,"method":"rules"}
    transaction = ("退款", "退钱", "取消订单", "取消预订", "改期", "修改订单", "换房", "改成双床", "改成大床", "升级房型", "延迟退房")
    if any(x in text for x in transaction):
        # A pure policy question is knowledge, an imperative/action request is a transaction.
        policy_question = any(x in text for x in ("政策", "规则", "能不能", "可以吗", "是否允许")) and not any(x in text for x in ("帮我", "给我", "现在就", "我要"))
        if not policy_question:
            return {"intent":"transaction_request","sub_intent":"booking_change_or_refund","entities":{},"confidence":0.98,"method":"rules"}
    complaint = ("投诉", "赔偿", "差评", "没人处理", "不回复", "态度差", "要求道歉")
    if any(x in text for x in complaint):
        return {"intent":"complaint","sub_intent":"service_complaint","entities":{},"confidence":0.98,"method":"rules"}
    realtime = ("现在还有", "当前还有", "今天还有", "实时", "剩余房量", "还有空房", "有空位吗", "现在有车位")
    if any(x in text for x in realtime) or (("现在" in text or "今天" in text) and any(x in text for x in ("车位","空房","房间","房")) and any(x in text for x in ("有","还有","剩"))):
        return {"intent":"realtime_availability","sub_intent":"inventory","entities":{},"confidence":0.98,"method":"rules"}
    order_cues = ("我预订", "我预定", "我订", "我的订单", "订单里的", "预订的", "预定的", "我之前订")
    order_fields = ("房型", "房间", "床型", "早餐", "停车", "权益", "入住日期", "退房日期", "几晚", "人数", "订单")
    if not no_booking and any(x in text for x in order_cues) and any(x in text for x in order_fields):
        return {"intent":"booking_related_inquiry","sub_intent":"booking_detail_or_entitlement","entities":{},"confidence":0.97,"method":"rules"}
    # Follow-up pronouns inherit only the prior topic, never prior authentication.
    if history and any(x in text for x in ("那呢", "那收费吗", "那什么时候", "它呢", "这个呢")):
        previous = history[-1] if isinstance(history[-1], dict) else {}
        prev_intent = previous.get("intent")
        if prev_intent == "booking_related_inquiry":
            return {"intent":"booking_related_inquiry","sub_intent":"contextual_booking_followup","entities":{},"confidence":0.82,"method":"context_rules"}
        if prev_intent == "public_knowledge_inquiry":
            return {"intent":"public_knowledge_inquiry","sub_intent":"contextual_faq_followup","entities":{},"confidence":0.8,"method":"context_rules"}
    service = ("送", "加被子", "毛巾", "维修", "不制冷", "打不开门", "打扫", "清洁", "补充用品", "换毛巾")
    if any(x in text for x in service):
        return {"intent":"service_request","sub_intent":"on_site_service","entities":{},"confidence":0.9,"method":"rules"}
    # Known negated booking question becomes a public-policy question.
    return {"intent":"public_knowledge_inquiry","sub_intent":"property_faq","entities":{},"confidence":0.72,"method":"rules"}

def classify_with_llm(query, history=None):
    key, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
    if not key or not model:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL") or None)
        prompt = {
            "current_message": query,
            "recent_context": (history or [])[-4:],
            "allowed_intents": sorted(INTENTS),
            "instructions": [
                "Classify the user's actual request, not isolated keywords.",
                "Distinguish public property policy from the user's own booking details or entitlements.",
                "A negated booking statement means no existing booking is asserted.",
                "A request for current room/parking inventory is realtime_availability.",
                "Requests to perform refunds or booking changes are transaction_request.",
                "Safety incidents always use safety_incident.",
                "If meaning cannot be determined, use ambiguous."
            ]
        }
        response = client.chat.completions.create(
            model=model, temperature=0,
            response_format={"type":"json_object"},
            messages=[
                {"role":"system","content":"Return one JSON object only with keys intent, sub_intent, entities. Do not make authorization decisions."},
                {"role":"user","content":json.dumps(prompt,ensure_ascii=False)}
            ])
        data=json.loads(response.choices[0].message.content or "{}")
        intent=data.get("intent")
        if intent not in INTENTS: return None
        return {"intent":intent,"sub_intent":str(data.get("sub_intent",""))[:80],
                "entities":data.get("entities") if isinstance(data.get("entities"),dict) else {},
                "confidence":None,"method":"llm"}
    except Exception:
        return None

def classify_intent(query, history=None):
    rules = classify_by_rules(query, history)
    # Deterministic high-risk and clear business patterns are never overridden by LLM.
    if rules["intent"] in {"safety_incident","transaction_request","realtime_availability","booking_related_inquiry","complaint","service_request"}:
        return rules
    llm = classify_with_llm(query, history)
    if llm and llm["intent"] != "ambiguous":
        return llm
    return rules
