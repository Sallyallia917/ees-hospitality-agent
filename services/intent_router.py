"""Deterministic business decision layer; LLM classification remains advisory."""
from services.semantic_classifier import classify_intent

def _make(intent, dependency, status, deps, knowledge, realtime, risk, action,
          response, reason, human=True, sub_intent=None, method="rules"):
    return {"intent": intent, "sub_intent": sub_intent, "classification_method": method,
            "order_dependency": dependency, "order_status": status, "data_dependencies": deps,
            "knowledge_required": knowledge, "realtime_data_required": realtime,
            "risk_level": risk, "action": action, "response": response,
            "reason": reason, "needs_human": human}

def route_question(query, context=None, history=None):
    context = context or {}
    status = context.get("order_status", "UNKNOWN")
    c = classify_intent(query, history, context)
    intent, sub, method = c["intent"], c.get("sub_intent"), c.get("method", "rules")
    if intent == "safety_incident":
        return _make(intent, "none", status, ["现场安全信息"], False, False, "critical",
            "safety_guidance", "请立即远离危险区域，不要自行操作或维修；如有燃气泄漏、起火或人身危险，请联系当地紧急服务及现场工作人员。",
            "安全事件优先于其他意图，直接进入安全响应。", True, sub, method)
    if intent == "booking_list_query":
        return _make(intent, "required", status, ["verified_identity", "booking_records"], False, False,
            "medium", "booking_list", "查询当前登录用户有权访问的订单列表；订单服务执行身份和归属校验。",
            "订单列表是个人数据，必须通过只读订单服务查询。", False, sub, method)
    if intent == "booking_selection":
        return _make(intent, "required", status, ["verified_identity", "dialogue_state", "booking_records"], False, False,
            "medium", "booking_selection", "根据当前会话候选订单解析用户选择，再由订单服务复核归属。",
            "仅允许从已认证订单列表中选择。", False, sub, method)
    if intent == "booking_issue":
        return _make(intent, "required", status, ["verified_identity", "booking_records"], False, False,
            "high", "transaction_handoff", "需要先确认具体订单，再了解错误内容并转人工核实。",
            "订单信息更正涉及交易数据，必须人工核验。", True, sub, method)
    if intent == "cancellation_policy_inquiry":
        return _make(intent, "required", status, ["verified_identity", "booking_details", "cancellation_policy"],
            False, False, "medium", "booking_policy_lookup",
            "读取本人所选订单绑定的取消政策并展示原始规则，不推断实时退款金额。",
            "取消政策咨询是只读查询，不等同于发起取消。", False, sub, method)
    if intent == "booking_related_inquiry":
        return _make(intent, "required", status, ["booking_details", "verified_identity", "booking_entitlements"],
            False, False, "medium", "booking_lookup",
            "个人订单信息由只读订单服务查询，并在服务端校验身份和订单归属。",
            "个人订单信息不得从公共 FAQ 推断。", False, sub, method)
    if intent == "transaction_request":
        return _make(intent, "required", status, ["verified_identity", "booking_details", "business_rules", "authorization"],
            False, False, "high", "transaction_handoff",
            "需要先确认具体订单和操作意图，确认后转人工；当前版本不执行取消、退款或订单变更。",
            "交易操作必须经过授权和业务系统执行；当前版本仅转人工。", True, sub, method)
    if intent in {"complaint", "service_request", "invoice_request"}:
        return _make(intent, "required", status, ["verified_identity", "booking_records", "ticket_details"],
            False, False, "high" if intent == "complaint" else "medium",
            "service_ticket_request",
            "先确认关联订单，再收集必要信息；向住客复述工单内容并确认后，创建对应类别的演示工单。",
            "投诉、住宿服务和票据申请是需要跟踪的住客事项，使用统一工单入口但按互斥主类别归档。",
            True, sub, method)
    if intent == "service_ticket_confirmation":
        return _make(intent, "required", status, ["verified_identity", "pending_ticket_request"],
            False, False, "medium", "service_ticket_confirmation",
            "确认后创建工单；拒绝则清除本次待提交事项。",
            "工单创建必须绑定明确的住客确认。", True, sub, method)
    if intent == "realtime_availability":
        return _make(intent, "none", status, ["realtime_inventory"], False, True, "medium",
            "human_escalation", "这个问题需要实时房态或现场资源数据。当前版本没有连接相关系统，无法确认当前库存，请联系工作人员核实。",
            "静态知识库不能证明实时库存。", True, sub, method)
    if intent == "complaint":
        return _make(intent, "optional", status, ["service_history"], False, False, "high",
            "human_escalation", "抱歉给您带来不好的体验。这类问题需要工作人员核实情况并跟进处理。当前版本不能查询服务记录或创建工单，请联系值班工作人员。",
            "投诉需要人工核实与跟进。", True, sub, method)
    if intent == "service_request":
        return _make(intent, "optional", status, ["service_capacity", "room_context"], False, False,
            "medium", "service_handoff", "我理解您需要现场服务。当前版本尚未连接服务工单系统，不能确认已安排人员，请联系现场工作人员确认处理。",
            "服务请求需要现场执行和状态跟踪；当前版本不创建工单。", True, sub, method)
    return _make("public_knowledge_inquiry", "none", status, ["property_knowledge"], True, False,
        "low", "rag_answer", "", "公共知识咨询进入门店知识库检索；若缺少知识证据，不应臆测回答。",
        False, sub, method)
