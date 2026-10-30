"""Deterministic business decision layer for EES MVP 1.2."""
from services.semantic_classifier import classify_intent

def _make(intent,dependency,status,deps,knowledge,realtime,risk,action,response,reason,human=True,sub_intent=None,method="rules"):
    return {"intent":intent,"sub_intent":sub_intent,"classification_method":method,"order_dependency":dependency,
      "order_status":status,"data_dependencies":deps,"knowledge_required":knowledge,"realtime_data_required":realtime,
      "risk_level":risk,"action":action,"response":response,"reason":reason,"needs_human":human}

def route_question(query,context=None,history=None):
    status=(context or {}).get("order_status","UNKNOWN")
    c=classify_intent(query,history); intent=c["intent"]; sub=c.get("sub_intent"); method=c.get("method","rules")
    if intent=="safety_incident":
        return _make(intent,"none",status,["现场安全信息"],False,False,"critical","safety_guidance",
          "请立即远离危险区域，不要自行操作或维修；如有燃气泄漏、起火或人身危险，请联系当地紧急服务及现场工作人员。",
          "安全事件优先于其他意图，直接进入安全响应。",True,sub,method)
    if intent=="booking_related_inquiry":
        action="order_tool_not_connected" if status=="VERIFIED" else "order_context_unavailable"
        response=("当前版本尚未接入订单查询工具，暂时无法读取订单详情。请通过原预订平台或门店工作人员核实。" if status=="VERIFIED" else
          "这个问题需要结合您的具体订单确认。当前版本没有接入订单系统，也无法验证订单归属，因此不能根据通用知识库推断您的房型或订单权益。请查看原预订平台订单详情，或联系门店工作人员核实。")
        return _make(intent,"required",status,["booking_details","verified_identity","booking_entitlements"],False,False,"medium",action,response,
          "个人订单信息和订单权益不得从公共 FAQ 推断；本版本不提供订单查询。",True,sub,method)
    if intent=="realtime_availability":
        return _make(intent,"none",status,["realtime_inventory"],False,True,"medium","human_escalation",
          "这个问题需要实时房态或现场资源数据。当前版本没有连接相关系统，无法确认当前库存，请联系工作人员核实。",
          "静态知识库不能证明实时库存。",True,sub,method)
    if intent=="transaction_request":
        return _make(intent,"required",status,["booking_details","business_rules","authorization"],False,True,"high","transaction_handoff",
          "这项请求可能改变订单或产生费用，需要核对订单渠道、条款和授权。当前版本不会执行订单变更或退款，请联系工作人员处理。",
          "交易操作必须经过授权和业务系统执行；当前版本仅转人工。",True,sub,method)
    if intent=="complaint":
        return _make(intent,"optional",status,["service_history"],False,False,"high","human_escalation",
          "抱歉给您带来不好的体验。这类问题需要工作人员核实情况并跟进处理。当前版本不能查询服务记录或创建工单，请联系值班工作人员。",
          "投诉需要人工核实与跟进。",True,sub,method)
    if intent=="service_request":
        return _make(intent,"optional",status,["service_capacity","room_context"],False,False,"medium","service_handoff",
          "我理解您需要现场服务。当前版本尚未连接服务工单系统，不能确认已安排人员，请联系现场工作人员确认处理。",
          "服务请求需要现场执行和状态跟踪；当前版本不创建工单。",True,sub,method)
    return _make("public_knowledge_inquiry","none",status,["property_knowledge"],True,False,"low","rag_answer","",
      "公共知识咨询进入门店知识库检索；若语义分类不确定，仍由知识检索证据决定是否回答。",False,sub,method)
