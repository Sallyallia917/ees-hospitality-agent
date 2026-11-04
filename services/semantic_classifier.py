"""Hybrid semantic intent classification.

Rules own safety, transaction, authorization-sensitive and real-time boundaries.
The optional LLM only interprets ambiguous language; it never authorizes actions.
"""
import json
import os
import re

INTENTS = {
    "public_knowledge_inquiry", "booking_related_inquiry", "booking_list_query",
    "booking_selection", "booking_issue", "realtime_availability",
    "transaction_request", "service_request", "complaint", "safety_incident",
    "ambiguous",
}

def _norm(text):
    return "".join(str(text or "").lower().split()).replace("？", "?")

def _result(intent, sub_intent, confidence, method="rules", entities=None):
    return {"intent": intent, "sub_intent": sub_intent, "entities": entities or {},
            "confidence": confidence, "method": method}

def classify_by_rules(query, history=None, context=None):
    text = _norm(query)
    history = history or []
    context = context or {}
    no_booking = any(x in text for x in (
        "还没预订", "还没有预订", "没有预订", "尚未预订", "没下单",
        "未下单", "还没订", "没有订房", "还没订房", "没有订单"
    ))

    # Safety always wins, including when a booking is also mentioned.
    if any(x in text for x in (
        "燃气", "煤气", "起火", "冒火花", "火花", "电线冒烟",
        "电线在冒烟", "漏电", "有人受伤", "火灾"
    )):
        return _result("safety_incident", "safety", 1.0)

    booking_ref = re.search(r"demo-booking-\d{4,}", text, re.IGNORECASE)
    if booking_ref:
        return _result("booking_related_inquiry", "booking_detail_by_id", 1.0,
                       entities={"booking_id": booking_ref.group(0).upper()})

    # Explicit list/count requests are distinct from a detail query.
    list_markers = ("我有几笔订单", "我有多少笔订单", "我的订单有几笔",
                    "列出我的订单", "查看我的订单", "我的订单列表",
                    "有哪些订单", "我订了几笔", "查一下我的订单")
    if not no_booking and any(x in text for x in list_markers):
        return _result("booking_list_query", "booking_list", .99)

    # Resolve ordinal selection only while a list is pending.
    if context.get("candidate_booking_ids"):
        ordinal = re.search(r"(?:第)?([一二三123])(?:笔|个|单|个订单)?", text)
        if ordinal or any(x in text for x in ("第一笔", "第二笔", "第三笔")):
            return _result("booking_selection", "select_booking", .99)

    # Booking errors are not public FAQ. Actual change/cancel is still handoff.
    if any(x in text for x in ("订单订错", "预定错误", "预订错误", "订错了",
                               "订单有误", "订单信息有误", "订单信息错", "订房订错", "预定订错")):
        return _result("booking_issue", "booking_error", .98)

    transaction_terms = (
        "退款", "退钱", "取消订单", "取消预订", "取消这笔预订", "取消这笔订单",
        "改期", "往后改", "往后调整", "修改订单", "换房", "换为双床",
        "换为大床", "换成双床房", "换成大床房", "换为双床房", "换为大床房",
        "改成双床", "改成大床", "改为双床", "改为大床", "换成双床",
        "换成大床", "升级房型", "延迟退房"
    )
    if any(x in text for x in transaction_terms):
        policy_question = any(x in text for x in (
            "政策", "规则", "能不能", "可以吗", "是否允许", "允不允许",
            "允许不允许", "可不可以", "酒店允许", "酒店可以", "酒店能"
        )) or (("允许" in text or "可以" in text) and ("吗" in text or "?" in text))
        explicit_execution = any(x in text for x in (
            "帮我", "请把", "给我", "现在就", "我要", "我想换", "替我", "帮忙把"
        ))
        if policy_question and not explicit_execution:
            return _result("public_knowledge_inquiry", "property_faq", .96)
        return _result("transaction_request", "booking_change_or_refund", .98)

    if any(x in text for x in (
        "投诉", "赔偿", "差评", "没人处理", "不回复", "态度差",
        "要求道歉", "反馈服务问题", "服务不满意", "不满意", "没回应", "未回应"
    )):
        return _result("complaint", "service_complaint", .98)

    # A personal possessive + a booking-specific field is sufficient.
    personal_markers = ("我的", "我订", "我预订", "我预定", "我之前", "我这单",
                        "订单", "这笔订单", "该订单", "预订的", "预定的")
    booking_fields = (
        "房型", "房间", "床型", "早餐", "含早", "停车", "权益",
        "入住日期", "入住时间", "退房日期", "退房时间", "几晚",
        "人数", "订单", "哪种床", "大床", "双床", "入住哪天", "住到哪天"
    )
    if not no_booking and any(x in text for x in personal_markers) and any(x in text for x in booking_fields):
        return _result("booking_related_inquiry", "booking_detail_or_entitlement", .97)

    # Short elliptical follow-ups inherit the previous domain only when state supports it.
    prev = history[-1] if history and isinstance(history[-1], dict) else {}
    previous_intent = prev.get("intent") or context.get("last_intent")
    has_active_booking = bool(context.get("active_booking_id"))
    if not no_booking and previous_intent in {
        "booking_related_inquiry", "booking_list_query", "booking_selection"
    } and (has_active_booking or context.get("candidate_booking_ids") or text.startswith("那") or any(x in text for x in ("它呢", "这个呢", "那呢"))):
        if any(x in text for x in (
            "早餐", "含早", "停车", "权益", "入住", "退房", "房型",
            "房间", "床型", "那", "这个", "它", "几晚", "人数"
        )):
            return _result("booking_related_inquiry", "contextual_booking_followup", .90, "context_rules")

    if any(x in text for x in (
        "现在还有", "当前还有", "今天还有", "今晚还有", "此刻有",
        "实时", "剩余房量", "还有空房", "有空位吗", "有位置吗", "现在有车位"
    )) or (("现在" in text or "今天" in text or "今晚" in text)
           and any(x in text for x in ("车位", "空房", "房间", "房"))
           and any(x in text for x in ("有", "还有", "剩"))):
        return _result("realtime_availability", "inventory", .98)

    if any(x in text for x in (
        "送", "加被子", "加一床被子", "加一床毯子", "毛巾", "维修",
        "不制冷", "打不开门", "打扫", "清洁", "补充用品", "换毛巾"
    )):
        return _result("service_request", "on_site_service", .90)

    return _result("public_knowledge_inquiry", "property_faq", .72)

def classify_with_llm(query, history=None, context=None):
    key, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
    if not key or not model:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL") or None)
        payload = {
            "message": query,
            "recent_context": (history or [])[-6:],
            "dialogue_state": {
                "active_booking_id": (context or {}).get("active_booking_id"),
                "candidate_booking_count": len((context or {}).get("candidate_booking_ids") or [])
            },
            "allowed_intents": sorted(INTENTS),
            "rules": [
                "Distinguish public property facts from personal booking facts.",
                "A personal booking query requires a later authenticated service lookup.",
                "Do not infer authentication or permission from user language.",
                "Current availability is realtime_availability.",
                "Changes, cancellation and refunds are handoff-only.",
                "A booking error/incorrect reservation is booking_issue.",
                "Use ambiguous when context is insufficient."
            ]
        }
        response = client.chat.completions.create(
            model=model, temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return JSON only: intent, sub_intent, entities. Interpret language only. Never authorize or execute."},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
            ]
        )
        data = json.loads(response.choices[0].message.content or "{}")
        if data.get("intent") not in INTENTS:
            return None
        return _result(data["intent"], str(data.get("sub_intent", ""))[:80], None,
                       "llm", data.get("entities") if isinstance(data.get("entities"), dict) else {})
    except Exception:
        return None

def classify_intent(query, history=None, context=None):
    rule = classify_by_rules(query, history, context)
    protected = {
        "safety_incident", "transaction_request", "realtime_availability",
        "booking_related_inquiry", "booking_list_query", "booking_selection",
        "booking_issue", "complaint", "service_request"
    }
    # Explicit and state-supported deterministic decisions are not overridden by LLM.
    if rule["intent"] in protected:
        return rule
    llm = classify_with_llm(query, history, context)
    if not llm or llm["intent"] == "ambiguous":
        return rule
    # LLM can only promote ambiguous/public language into a personal booking query;
    # all subsequent data access still passes deterministic identity and ownership checks.
    if llm["intent"] in {"booking_related_inquiry", "booking_list_query", "booking_issue"}:
        return llm
    return rule
