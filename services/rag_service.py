import os, re
from services.retrieval import search_knowledge
LIVE=("空房","房态","还有房吗","有房吗","今天有房","实时房态","当前房态")
UNSUPPORTED=("机场接送","接送机","接机","送机")
ORDER_TERMS=("我的订单","订单","预订","预定","我订","订的","booking")
ROOM_TERMS=("房型","房间类型","床型","大床房","双床房","房间")
LIVE_ROOM=("还有什么房型","可选房型","有哪些房型","房型有哪些","剩余房型","当前房型")
CRITICAL=("燃气","煤气","插座冒火花","起火","电线冒烟")

def _result(answer,hits,grounded,needs_human,reason,action):
    return {"answer":answer,"knowledge_ids":[h["knowledge_id"] for h in hits],"sources":[{"knowledge_id":h["knowledge_id"],"source":h["source"],"category":h.get("category"),"score":h.get("score")} for h in hits],"grounded":grounded,"needs_human":needs_human,"reason":reason,"action":action}

def answer_question(query,property_id,knowledge_base,threshold=2.0):
    normalized=query.lower().replace(" ","")
    # Order-specific attributes must never be answered from generic FAQ retrieval.
    order_room_query=(
        any(t in normalized for t in ORDER_TERMS)
        and any(t in normalized for t in ROOM_TERMS)
        and any(t in normalized for t in ("什么","哪","哪个","是否","是不是","我订","订的","订单"))
    )
    if order_room_query:
        return _result("你预订的具体房型属于个人订单信息。当前 MVP 1 没有连接预订平台或 PMS，无法读取你的订单，因此不能根据通用 FAQ 推断房型。请查看原预订平台的订单详情，或联系门店工作人员核实。",[],False,True,"订单专属信息不可从通用知识库获取","order_lookup_unavailable")
    if any(t in normalized for t in LIVE_ROOM):
        return _result("当前系统没有连接实时房态或预订系统，无法查询可选房型及剩余房量。请联系工作人员或原预订平台核实。",[],False,True,"动态房型与房态不可查询","human_escalation")
    if any(t in query for t in LIVE):
        return _result("当前系统没有连接实时房态或预订系统，无法确认是否有空房。请联系工作人员或原预订平台核实。",[],False,True,"动态房态不可查询","human_escalation")
    if any(t in query for t in UNSUPPORTED):
        return _result("当前演示知识库没有经过核实的接送服务信息，请联系工作人员确认。",[],False,True,"未配置接送服务知识","human_escalation")
    hits=search_knowledge(query,property_id,knowledge_base,3)
    if any(t in query for t in CRITICAL) or ("插座" in query and "火花" in query):
        safe=[h for h in hits if h.get("risk_level")=="critical"]
        if safe:return _result(safe[0]["answer"],[safe[0]],True,False,"命中安全知识","safety_guidance")
        return _result("这可能涉及安全风险。请先远离危险区域，并联系当地紧急服务及现场工作人员，不要等待在线客服回复。",[],False,True,"安全兜底","human_escalation")
    if not hits or hits[0]["score"]<threshold:
        return _result("当前演示知识库没有足够依据确认这个问题。为避免提供错误信息，建议联系工作人员核实。",hits,False,True,"证据不足","human_escalation")
    h=hits[0]
    return _result(h["answer"],[h],True,h.get("risk_level") in {"high","critical"},"命中当前门店有效知识","answer_with_escalation" if h.get("risk_level")=="high" else "answer")

def generate_with_optional_llm(query,result):
    key=os.getenv("LLM_API_KEY"); model=os.getenv("LLM_MODEL")
    if not key or not model or not result["grounded"]:return result
    try:
        from openai import OpenAI
        client=OpenAI(api_key=key,base_url=os.getenv("LLM_BASE_URL") or None)
        response=client.chat.completions.create(model=model,temperature=0,messages=[
          {"role":"system","content":"你是住宿服务知识助手。只能改写给定证据，不得添加事实、价格、时间或承诺。"},
          {"role":"user","content":f"问题：{query}\\n证据：{result['answer']}\\n是否需要人工：{result['needs_human']}"}])
        answer=response.choices[0].message.content
        return {**result,"answer":answer.strip(),"generation_mode":"llm_rewrite"} if answer else result
    except Exception as exc:return {**result,"llm_error":str(exc),"generation_mode":"deterministic_fallback"}
