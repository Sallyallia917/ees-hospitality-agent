"""Hybrid semantic intent classification with deterministic transaction boundaries."""
import json
import os
import re

INTENTS = {
    "public_knowledge_inquiry", "booking_related_inquiry", "booking_list_query",
    "booking_selection", "booking_issue", "realtime_availability",
    "transaction_request", "cancellation_policy_inquiry", "service_request",
    "complaint", "invoice_request", "service_ticket_confirmation", "safety_incident", "ambiguous",
}

def _norm(text):
    return "".join(str(text or "").lower().split()).replace("？", "?")

def _result(intent, sub_intent, confidence, method="rules", entities=None):
    return {"intent": intent, "sub_intent": sub_intent, "entities": entities or {},
            "confidence": confidence, "method": method}

def _policy_question(text):
    terms = ("取消政策", "取消规则", "退款政策", "退款规则", "能取消吗",
             "可以取消吗", "能不能取消", "可不可以取消", "是否可以取消",
             "取消会扣钱吗", "取消要收费吗")
    return any(x in text for x in terms) or (
        any(x in text for x in ("改成", "改为", "换成", "换为")) and
        any(x in text for x in ("酒店允许", "酒店可以", "是否允许", "能不能", "可以吗")) and
        not any(x in text for x in ("帮我", "请把", "我要", "我想"))
    ) or (
        any(x in text for x in ("取消", "退款")) and
        any(x in text for x in ("政策", "规则", "能吗", "可以吗", "可不可以", "能不能"))
    )

def _transaction_request(text):
    terms = ("我要取消", "帮我取消", "请取消", "申请取消", "取消订单",
             "取消预订", "取消预定", "取消我预订", "取消我预定",
             "我要退款", "帮我退款", "申请退款", "取消退款", "退款", "退钱", "办理退款", "现在给我退款",
             "改期", "往后改", "往后调整", "修改订单", "换房", "升级房型", "延迟退房", "换为双床", "换为大床", "换成双床", "换成大床", "改成双床", "改成大床", "改为双床", "改为大床", "改为双床房", "改为大床房", "改成双床房", "改成大床房", "换成双床房", "换成大床房", "我想换成", "我想改成", "我想改期")
    return any(x in text for x in terms)

def classify_by_rules(query, history=None, context=None):
    text = _norm(query)
    history, context = history or [], context or {}
    no_booking = any(x in text for x in ("还没预订", "没有预订", "尚未预订", "没下单", "未下单", "没有订单"))

    if any(x in text for x in ("燃气", "煤气", "起火", "冒火花", "火花", "电线冒烟", "电线在冒烟", "漏电", "有人受伤", "火灾")):
        return _result("safety_incident", "safety", 1.0)

    if _policy_question(text):
        personal = any(x in text for x in ("我的", "我订", "我预订", "我预定", "订单", "房源", "房间", "这笔"))
        if personal or context.get("active_booking_id") or context.get("candidate_booking_ids"):
            return _result("cancellation_policy_inquiry", "booking_cancellation_policy", .99)
        return _result("public_knowledge_inquiry", "property_cancellation_policy", .90)

    if context.get("candidate_booking_ids"):
        ordinal = re.search(r"(?:第)?([一二三123])(?:笔|个|单|个订单)?", text)
        if ordinal:
            return _result("booking_selection", "select_booking", .99)
        candidates = context.get("candidate_booking_summaries") or []
        matches = []
        for row in candidates:
            values = [row.get("room_type"), row.get("property_name"), row.get("property_id"),
                      str(row.get("check_in") or "")[:10], str(row.get("check_out") or "")[:10]]
            if any(v and len(str(v)) >= 2 and (str(v).lower() in text or text in str(v).lower()) for v in values):
                matches.append(row)
        if len(matches) == 1:
            return _result("booking_selection", "select_booking_by_attribute", .98,
                           entities={"booking_id": matches[0]["booking_id"]})
        if len(matches) > 1:
            return _result("booking_selection", "ambiguous_booking_selection", .90)

    if context.get("pending_action") == "collect_invoice_details":
        return _result("invoice_request", "invoice_details", .99)
    if context.get("pending_action") == "confirm_service_ticket":
        if any(x in text for x in ("确认", "是的", "没错", "对", "确定", "提交")):
            return _result("service_ticket_confirmation", "confirm_ticket", .99)
        if any(x in text for x in ("算了", "取消", "不需要", "先不用", "不确认")):
            return _result("service_ticket_confirmation", "reject_ticket", .99)
        return _result("service_ticket_confirmation", "supplement_ticket_details", .90)
    if context.get("pending_action") == "confirm_transaction":
        if any(x in text for x in ("是", "确认", "没错", "对的", "就是这笔", "确定")):
            return _result("transaction_request", "confirm_transaction", .99)
        if any(x in text for x in ("不是", "不对", "算了", "取消操作", "先不")):
            return _result("transaction_request", "reject_transaction", .99)
    if context.get("pending_action") == "describe_booking_issue":
        return _result("booking_issue", "issue_details", .95)

    booking_ref = re.search(r"demo-booking-\d{4,}", text, re.IGNORECASE)
    if booking_ref:
        return _result("booking_related_inquiry", "booking_detail_by_id", 1.0,
                       entities={"booking_id": booking_ref.group(0).upper()})

    list_markers = ("我有几笔订单", "我有多少笔订单", "我的订单有几笔",
                    "列出我的订单", "查看我的订单", "我的订单列表",
                    "有哪些订单", "我订了几笔", "查一下我的订单")
    if not no_booking and any(x in text for x in list_markers):
        return _result("booking_list_query", "booking_list", .99)

    if any(x in text for x in ("订单订错", "预定错误", "预订错误", "订错了", "订单有误", "订单信息有误", "订单信息错", "订房订错", "预定订错")) and any(x in text for x in ("退款", "退钱", "取消订单", "申请取消")):
        return _result("transaction_request", "booking_error_refund", .99)

    if any(x in text for x in ("订单订错", "预定错误", "预订错误", "订错了",
                               "订单有误", "订单信息有误", "订单信息错", "订房订错", "预定订错")):
        return _result("booking_issue", "booking_error", .98)

    if _policy_question(text):
        personal = any(x in text for x in ("我的", "我订", "我预订", "我预定", "订单", "房源", "房间", "这笔"))
        if personal or context.get("active_booking_id") or context.get("candidate_booking_ids"):
            return _result("cancellation_policy_inquiry", "booking_cancellation_policy", .99)
        return _result("public_knowledge_inquiry", "property_cancellation_policy", .90)

    if _transaction_request(text):
        change_terms = ("改期", "往后改", "往后调整", "修改订单", "换房", "升级房型", "延迟退房", "换为", "换成", "改成", "改为")
        sub_intent = "booking_change_or_refund" if any(x in text for x in change_terms) else "booking_cancel_or_refund"
        return _result("transaction_request", sub_intent, .99)

    if any(x in text for x in ("你不记得", "我刚才说过", "我之前说过", "之前不是", "刚才提过")):
        return _result("complaint", "history_reference_complaint", .94, "context_rules")

    if any(x in text for x in ("发票", "开发票", "开票", "票据", "抬头", "税号")):
        return _result("invoice_request", "invoice", .98)
    if any(x in text for x in ("投诉", "赔偿", "差评", "卫生太差", "脏乱差", "很脏", "吵得睡不着", "房间吵", "噪音", "没有电梯还")):
        return _result("complaint", "experience_complaint", .98)
    if any(x in text for x in ("投诉", "赔偿", "差评", "没人处理", "不回复", "态度差",
                               "要求道歉", "反馈服务问题", "服务不满意", "不满意", "没回应", "未回应")):
        return _result("complaint", "service_complaint", .98)

    personal_markers = ("我的", "我订", "我预订", "我预定", "我之前", "我这单",
                        "订单", "这笔订单", "该订单", "预订的", "预定的", "订房时选")
    booking_fields = ("房型", "房间", "床型", "早餐", "含早", "停车", "权益",
                      "入住日期", "入住时间", "退房日期", "退房时间", "几晚",
                      "人数", "订单", "哪种床", "大床", "双床", "入住哪天", "住到哪天")
    if not no_booking and any(x in text for x in personal_markers) and any(x in text for x in booking_fields):
        return _result("booking_related_inquiry", "booking_detail_or_entitlement", .97)

    prev = history[-1] if history and isinstance(history[-1], dict) else {}
    previous_intent = prev.get("intent") or context.get("last_intent")
    if not no_booking and previous_intent in {
        "booking_related_inquiry", "booking_list_query", "booking_selection",
        "cancellation_policy_inquiry", "transaction_request", "booking_issue"
    } and (context.get("active_booking_id") or context.get("candidate_booking_ids") or text.startswith("那") or any(x in text for x in ("它呢", "这个呢", "那呢"))):
        if any(x in text for x in ("早餐", "含早", "停车", "权益", "入住", "退房", "房型",
                                   "房间", "床型", "取消", "退款", "那", "这个", "它", "日期")):
            return _result("booking_related_inquiry", "contextual_booking_followup", .90, "context_rules")

    if (("现在" in text or "今天" in text or "今晚" in text) and any(x in text for x in ("车位", "空房", "房间", "房")) and any(x in text for x in ("有", "还有", "剩"))):
        return _result("realtime_availability", "inventory", .98)
    if any(x in text for x in ("现在还有", "当前还有", "今天还有", "今晚还有", "此刻有",
                               "实时", "剩余房量", "还有空房", "有空位吗", "有位置吗", "现在有车位")):
        return _result("realtime_availability", "inventory", .98)
    if any(x in text for x in ("送", "加被子", "加一床被子", "加一床毯子", "毛巾", "维修",
                               "不制冷", "打不开门", "打扫", "清洁", "补充用品", "换毛巾",
                               "空调", "房间脏", "卫生不好", "房间吵", "噪音", "没有电梯")):
        if any(x in text for x in ("有电梯吗", "有没有电梯", "没有电梯吗", "酒店电梯", "设施有哪些")):
            return _result("public_knowledge_inquiry", "facility_question", .96)
        if text in ("没有电梯", "酒店没电梯", "房源没电梯"):
            return _result("service_request", "facility_or_complaint_clarification", .70)
        if any(x in text for x in ("投诉", "太差", "脏乱差", "影响休息", "无法接受", "要求处理", "反馈")):
            return _result("complaint", "experience_complaint", .96)
        return _result("service_request", "on_site_service", .90)
    return _result("public_knowledge_inquiry", "property_faq", .72)

def classify_with_llm(query, history=None, context=None):
    key, model = os.getenv("LLM_API_KEY"), os.getenv("LLM_MODEL")
    if not key or not model:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL") or None)
        payload = {"message": query, "recent_context": (history or [])[-6:],
                   "dialogue_state": {"active_booking_id": (context or {}).get("active_booking_id"),
                   "candidate_booking_count": len((context or {}).get("candidate_booking_ids") or [])},
                   "allowed_intents": sorted(INTENTS)}
        response = client.chat.completions.create(model=model, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": "Return JSON only: intent, sub_intent, entities. Interpret language only; never authorize or execute."},
                      {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        data = json.loads(response.choices[0].message.content or "{}")
        if data.get("intent") not in INTENTS:
            return None
        return _result(data["intent"], str(data.get("sub_intent", ""))[:80], None, "llm",
                       data.get("entities") if isinstance(data.get("entities"), dict) else {})
    except Exception:
        return None

def classify_intent(query, history=None, context=None):
    rule = classify_by_rules(query, history, context)
    protected = {"safety_incident", "transaction_request", "realtime_availability",
                 "booking_related_inquiry", "booking_list_query", "booking_selection",
                 "booking_issue", "cancellation_policy_inquiry", "complaint", "service_request", "invoice_request", "service_ticket_confirmation"}
    if rule["intent"] in protected:
        return rule
    llm = classify_with_llm(query, history, context)
    if not llm or llm["intent"] == "ambiguous":
        return rule
    if llm["intent"] in {"booking_related_inquiry", "booking_list_query", "booking_issue",
                         "cancellation_policy_inquiry"}:
        return llm
    return rule
