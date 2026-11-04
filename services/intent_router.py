"""Deterministic business decision layer; LLM classification remains advisory."""
from services.semantic_classifier import classify_intent

def _make(intent, dependency, status, deps, knowledge, realtime, risk, action,
          response, reason, human=True, sub_intent=None, method="rules"):
    return {
        "intent": intent, "sub_intent": sub_intent, "classification_method": method,
        "order_dependency": dependency, "order_status": status, "data_dependencies": deps,
        "knowledge_required": knowledge, "realtime_data_required": realtime,
        "risk_level": risk, "action": action, "response": response,
        "reason": reason, "needs_human": human
    }

def route_question(query, context=None, history=None):
    context = context or {}
    status = context.get("order_status", "UNKNOWN")
    c = classify_intent(query, history, context)
    intent, sub, method = c["intent"], c.get("sub_intent"), c.get("method", "rules")

    if intent == "safety_incident":
        return _make(intent, "none", status, ["现场安全信息"], False, False, "critical",
            "safety_guidance",
            "请立即远离危险区域，不要自行操作或维修；如有燃气泄漏、起火或人身危险，请联系当地紧急服务及现场工作人员。",
            "安全事件优先于其他意图，直接进入安全响应。", True, sub, method)
    if intent == "booking_list_query":
        return _make(intent, "required", status, ["verified_identity", "booking_records"],
            False, False, "medium", "booking_list",
            "查询当前登录用户有权访问的订单列表；订单服务执行身份和归属校验。",
            "订单列表是个人数据，必须通过只读订单服务查询。", False, sub, method)
    if intent == "booking_selection":
        return _make(intent, "required", status, ["verified_identity", "dialogue_state", "booking_records"],
            False, False, "medium", "booking_selection",
            "根据待选择订单列表解析用户选择，再由订单服务复核归属。",
            "序号仅用于选择当前会话已展示的候选订单。", False, sub, method)
    if intent == "booking_issue":
        return _make(intent, "required", status, ["verified_identity", "booking_records"],
            False, False, "high", "transaction_handoff",
            "您提到订单信息可能有误。当前版本不会直接修改订单，请联系工作人员核对订单记录并处理。",
            "订单错误涉及交易数据更正，需人工核验；不从 FAQ 推断或修改。", True, sub, method)
    if intent == "booking_related_inquiry":
        return _make(intent, "required", status,
            ["booking_details", "verified_identity", "booking_entitlements"],
            False, False, "medium", "booking_lookup",
            "个人订单信息由只读订单服务查询，并在服务端校验身份和订单归属。",
            "个人订单信息不得从公共 FAQ 推断；通过只读订单服务查询。", False, sub, method)
    if intent == "realtime_availability":
        return _make(intent, "none", status, ["realtime_inventory"], False, True, "medium",
            "human_escalation",
            "这个问题需要实时房态或现场资源数据。当前版本没有连接相关系统，无法确认当前库存，请联系工作人员核实。",
            "静态知识库不能证明实时库存。", True, sub, method)
    if intent == "transaction_request":
        return _make(intent, "required", status, ["booking_details", "business_rules", "authorization"],
            False, True, "high", "transaction_handoff",
            "这项请求可能改变订单或产生费用，需要核对订单渠道、条款和授权。当前版本不会执行订单变更或退款，请联系工作人员处理。",
            "交易操作必须经过授权和业务系统执行；当前版本仅转人工。", True, sub, method)
    if intent == "complaint":
        return _make(intent, "optional", status, ["service_history"], False, False, "high",
            "human_escalation",
            "抱歉给您带来不好的体验。这类问题需要工作人员核实情况并跟进处理。当前版本不能查询服务记录或创建工单，请联系值班工作人员。",
            "投诉需要人工核实与跟进。", True, sub, method)
    if intent == "service_request":
        return _make(intent, "optional", status, ["service_capacity", "room_context"], False, False,
            "medium", "service_handoff",
            "我理解您需要现场服务。当前版本尚未连接服务工单系统，不能确认已安排人员，请联系现场工作人员确认处理。",
            "服务请求需要现场执行和状态跟踪；当前版本不创建工单。", True, sub, method)
    return _make("public_knowledge_inquiry", "none", status, ["property_knowledge"],
        True, False, "low", "rag_answer", "",
        "公共知识咨询进入门店知识库检索；若缺少知识证据，不应臆测回答。",
        False, sub, method)
