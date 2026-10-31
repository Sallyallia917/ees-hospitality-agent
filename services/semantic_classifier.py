"""Hybrid intent classification: deterministic rules first, optional LLM for ambiguous input.
LLM output is advisory; business authorization and routing remain deterministic.
"""
import json, os
INTENTS={"public_knowledge_inquiry","booking_related_inquiry","realtime_availability","transaction_request","service_request","complaint","safety_incident","ambiguous"}

def _norm(text):
    return "".join(str(text or "").lower().split()).replace("？","?")

def classify_by_rules(query, history=None):
    text=_norm(query); history=history or []
    no_booking=any(x in text for x in ("还没预订","还没有预订","没有预订","尚未预订","没下单","未下单","还没订","没有订房"))
    if any(x in text for x in ("燃气","煤气","起火","冒火花","火花","电线冒烟","电线在冒烟","漏电","有人受伤","火灾")):
        return {"intent":"safety_incident","sub_intent":"safety","entities":{},"confidence":1.0,"method":"rules"}
    transaction=("退款","退钱","取消订单","取消预订","改期","修改订单","换房","改成双床","改成大床","改为双床","改为大床","换成双床","换成大床","升级房型","延迟退房")
    if any(x in text for x in transaction):
        policy=any(x in text for x in ("政策","规则","能不能","可以吗","是否允许","是否允许","允不允许","允许不允许","可不可以")) and not any(x in text for x in ("帮我","给我","现在就","我要"))
        if not policy:
            return {"intent":"transaction_request","sub_intent":"booking_change_or_refund","entities":{},"confidence":.98,"method":"rules"}
    if any(x in text for x in ("投诉","赔偿","差评","没人处理","不回复","态度差","要求道歉","反馈服务问题","服务不满意","不满意")):
        return {"intent":"complaint","sub_intent":"service_complaint","entities":{},"confidence":.98,"method":"rules"}
    if any(x in text for x in ("现在还有","当前还有","今天还有","今晚还有","此刻有","实时","剩余房量","还有空房","有空位吗","有位置吗","现在有车位")) or (("现在" in text or "今天" in text or "今晚" in text) and any(x in text for x in ("车位","空房","房间","房")) and any(x in text for x in ("有","还有","剩"))):
        return {"intent":"realtime_availability","sub_intent":"inventory","entities":{},"confidence":.98,"method":"rules"}
    order_cues=("我预订","我预定","我订","我的订单","订单里的","预订的","预定的","我之前订","我之前下的单","我这单","订单有没有","订房时选")
    order_fields=("房型","房间","床型","早餐","含早","停车","权益","入住日期","退房日期","几晚","人数","订单","哪种床","大床","双床")
    if not no_booking and any(x in text for x in order_cues) and any(x in text for x in order_fields):
        return {"intent":"booking_related_inquiry","sub_intent":"booking_detail_or_entitlement","entities":{},"confidence":.97,"method":"rules"}
    if history and (text.startswith("那") or any(x in text for x in ("它呢","这个呢","那呢"))):
        prev=history[-1] if isinstance(history[-1],dict) else {}
        if prev.get("intent")=="booking_related_inquiry":
            return {"intent":"booking_related_inquiry","sub_intent":"contextual_booking_followup","entities":{},"confidence":.82,"method":"context_rules"}
        if prev.get("intent")=="public_knowledge_inquiry":
            return {"intent":"public_knowledge_inquiry","sub_intent":"contextual_faq_followup","entities":{},"confidence":.8,"method":"context_rules"}
    if any(x in text for x in ("送","加被子","毛巾","维修","不制冷","打不开门","打扫","清洁","补充用品","换毛巾")):
        return {"intent":"service_request","sub_intent":"on_site_service","entities":{},"confidence":.9,"method":"rules"}
    return {"intent":"public_knowledge_inquiry","sub_intent":"property_faq","entities":{},"confidence":.72,"method":"rules"}

def classify_with_llm(query, history=None):
    key,model=os.getenv("LLM_API_KEY"),os.getenv("LLM_MODEL")
    if not key or not model: return None
    try:
        from openai import OpenAI
        client=OpenAI(api_key=key,base_url=os.getenv("LLM_BASE_URL") or None)
        payload={"message":query,"recent_context":(history or [])[-4:],"allowed_intents":sorted(INTENTS),
          "rules":["Distinguish public property policy from personal booking facts/entitlements.",
          "Negated booking statements do not imply an existing booking.","Current inventory is realtime_availability.",
          "Refund/change execution requests are transaction_request.","Safety incidents are safety_incident.",
          "Use ambiguous if meaning is unclear."]}
        response=client.chat.completions.create(model=model,temperature=0,response_format={"type":"json_object"},
          messages=[{"role":"system","content":"Return JSON only with intent, sub_intent, entities. Do not authorize actions."},
                    {"role":"user","content":json.dumps(payload,ensure_ascii=False)}])
        data=json.loads(response.choices[0].message.content or "{}")
        if data.get("intent") not in INTENTS: return None
        return {"intent":data["intent"],"sub_intent":str(data.get("sub_intent",""))[:80],
          "entities":data.get("entities") if isinstance(data.get("entities"),dict) else {},"confidence":None,"method":"llm"}
    except Exception: return None

def classify_intent(query,history=None):
    rule=classify_by_rules(query,history)
    if rule["intent"] in {"safety_incident","transaction_request","realtime_availability","booking_related_inquiry","complaint","service_request"}:
        return rule
    llm=classify_with_llm(query,history)
    return llm if llm and llm["intent"]!="ambiguous" else rule
