import pytest
from services.intent_router import route_question

@pytest.mark.parametrize("q",[
 "我之前订的那个房间是什么房型？","我订单里的早餐包含吗？","我订的房间能停车吗？",
 "我预定的是大床还是双床？","我的订单入住日期是哪天？"
])
def test_personal_booking_queries_never_enter_rag(q):
    r=route_question(q)
    assert r["intent"]=="booking_related_inquiry"
    assert r["action"]=="order_context_unavailable"
    assert r["knowledge_required"] is False

@pytest.mark.parametrize("q",[
 "我还没预订，停车收费吗？","我没有预订，早餐几点开始？","尚未预订，酒店有停车场吗？"
])
def test_negated_booking_is_public_faq(q):
    assert route_question(q)["action"]=="rag_answer"

@pytest.mark.parametrize("q",[
 "现在停车场还有空位吗？","今天还有双床房吗？","当前还有空房吗？"
])
def test_realtime_inventory_never_uses_static_faq(q):
    r=route_question(q)
    assert r["intent"]=="realtime_availability" and r["action"]=="human_escalation"

@pytest.mark.parametrize("q",["帮我退钱","请帮我取消预订","把我的大床房改成双床房","我要改期"])
def test_transactions_are_handoff_only(q):
    assert route_question(q)["action"]=="transaction_handoff"

@pytest.mark.parametrize("q",["闻到煤气味怎么办","插座突然冒火花","房间电线冒烟了"])
def test_safety_overrides_other_topics(q):
    r=route_question(q)
    assert r["risk_level"]=="critical" and r["action"]=="safety_guidance"

def test_contextual_booking_followup_inherits_booking_intent_but_not_auth():
    r=route_question("那停车收费吗？",history=[{"intent":"booking_related_inquiry"}])
    assert r["intent"]=="booking_related_inquiry" and r["action"]=="order_context_unavailable"

def test_contextual_public_followup_remains_public_faq():
    assert route_question("那收费吗？",history=[{"intent":"public_knowledge_inquiry"}])["action"]=="rag_answer"

def test_combined_booking_and_public_question_is_conservatively_blocked():
    assert route_question("我预订的房间有早餐吗？早餐几点开始？")["action"]=="order_context_unavailable"

def test_verified_context_does_not_fake_order_lookup():
    assert route_question("我预订的是什么房型？",{"order_status":"VERIFIED"})["action"]=="order_tool_not_connected"

def test_classifier_metadata_is_exposed_for_audit():
    r=route_question("酒店几点入住？")
    assert r["classification_method"] in {"rules","llm"} and r["sub_intent"]


@pytest.mark.parametrize("q",[
    "帮我把大床房改为双床房",
    "请把房间改为双床",
    "我想换成大床房",
    "把我的大床房改成双床房"
])
def test_room_type_change_requests_are_transaction_handoff(q):
    r=route_question(q)
    assert r["intent"]=="transaction_request"
    assert r["action"]=="transaction_handoff"
    assert r["order_dependency"]=="required"

def test_room_type_change_policy_question_can_use_public_knowledge(q="酒店是否允许把大床改成双床？"):
    r=route_question(q)
    assert r["intent"]=="public_knowledge_inquiry"
    assert r["action"]=="rag_answer"
