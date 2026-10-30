SAFETY_TERMS = ("燃气", "煤气", "起火", "冒火花", "电线冒烟")
ORDER_CUES = ("我预订", "我预定", "我订", "我的订单", "订单里的", "预订的", "预定的")
ORDER_FIELDS = ("房型", "房间", "床型", "早餐", "停车", "权益", "入住日期", "退房日期", "几晚", "人数")
LIVE_TERMS = ("现在还有", "当前还有", "实时", "剩余房量", "还有空房", "现在有车位")
TRANSACTION_TERMS = ("退款", "退钱", "取消订单", "取消预订", "修改订单", "改期", "换房", "改成", "更换房型", "帮我升级")
COMPLAINT_TERMS = ("投诉", "赔偿", "差评", "没人处理", "不回复")
SERVICE_TERMS = ("送", "加被子", "毛巾", "维修", "不制冷", "打不开门", "打扫")

def _make(intent, dependency, status, deps, knowledge, realtime, risk, action, response, reason, human=True):
    return {"intent": intent, "order_dependency": dependency, "order_status": status,
            "data_dependencies": deps, "knowledge_required": knowledge,
            "realtime_data_required": realtime, "risk_level": risk, "action": action,
            "response": response, "reason": reason, "needs_human": human}

def route_question(query, context=None):
    text = query.lower().replace(" ", "")
    status = (context or {}).get("order_status", "UNKNOWN")
    has = lambda terms: any(term in text for term in terms)
    if has(SAFETY_TERMS):
        return _make("safety_incident", "none", status, ["现场安全信息"], False, False, "critical",
          "safety_guidance", "请立即远离危险区域，不要自行操作或维修；如有燃气泄漏、起火或人身危险，请联系当地紧急服务及现场工作人员。",
          "安全风险优先处理。")
    if has(ORDER_CUES) and has(ORDER_FIELDS):
        deps = ["booking_details", "verified_identity"]
        if has(("停车", "早餐", "权益")): deps.append("booking_entitlements")
        if has(("房型", "房间", "床型")): deps.append("room_type")
        if status != "VERIFIED":
            return _make("booking_related_inquiry", "required", status, deps, False, False, "medium",
              "order_context_unavailable", "这个问题需要结合您的具体订单确认。当前版本没有接入订单系统，也无法验证订单归属，因此不能根据通用知识库推断您的房型或订单权益。请查看原预订平台订单详情，或联系门店工作人员核实。",
              "个人订单问题不能由公共 FAQ 推断。")
        return _make("booking_related_inquiry", "required", status, deps, False, False, "medium",
          "order_tool_not_connected", "当前版本尚未接入订单查询工具，暂时无法读取订单详情。请通过原预订平台或门店工作人员核实。",
          "身份验证状态不能替代订单查询服务。")
    if has(LIVE_TERMS):
        return _make("realtime_availability", "none", status, ["realtime_inventory"], False, True, "medium",
          "human_escalation", "这个问题需要实时房态或现场资源数据。当前版本没有连接相关系统，无法确认当前库存，请联系工作人员核实。",
          "实时库存不能由静态知识库回答。")
    if has(TRANSACTION_TERMS):
        return _make("transaction_request", "optional", status, ["booking_details", "business_rules", "authorization"], True, True, "high",
          "transaction_handoff", "这项请求可能改变订单或产生费用，需要核对订单渠道、条款和授权。当前版本不会执行订单变更或退款，请联系工作人员处理。",
          "交易操作必须经过授权和业务系统执行。")
    if has(COMPLAINT_TERMS):
        return _make("complaint", "optional", status, ["service_history"], False, False, "high",
          "human_escalation", "抱歉给您带来不好的体验。这类问题需要工作人员核实情况并跟进处理。当前版本不能查询服务记录或创建工单，请联系值班工作人员。",
          "投诉需要人工核实。")
    if has(SERVICE_TERMS):
        return _make("service_request", "optional", status, ["service_capacity", "room_context"], False, False, "medium",
          "service_handoff", "我理解您需要现场服务。当前版本尚未连接服务工单系统，不能确认已安排人员，请联系现场工作人员确认处理。",
          "服务请求需要实际执行和状态跟踪。")
    return _make("public_knowledge_inquiry", "none", status, ["property_knowledge"], True, False, "low",
      "rag_answer", "", "公共知识咨询可以进入门店知识库检索。", False)
