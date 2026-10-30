from services.intent_router import route_question
from services.context_manager import default_context, update_order_status

def test_public_parking_question_does_not_require_order():
    r=route_question("酒店有停车场吗？")
    assert r["intent"]=="public_knowledge_inquiry" and r["action"]=="rag_answer"
    assert r["order_dependency"]=="none"

def test_booking_parking_entitlement_requires_order():
    r=route_question("我预订的房型有停车位吗？")
    assert r["intent"]=="booking_related_inquiry"
    assert r["order_dependency"]=="required"
    assert "booking_entitlements" in r["data_dependencies"]
    assert r["action"]=="order_context_unavailable"

def test_user_claim_does_not_authenticate_order():
    r=route_question("我订单里包含早餐吗？",{"order_status":"UNVERIFIED"})
    assert r["action"]=="order_context_unavailable"

def test_verified_status_does_not_fake_booking_tool():
    ctx=update_order_status(default_context(),"VERIFIED")
    assert route_question("我预订的是什么房型？",ctx)["action"]=="order_tool_not_connected"

def test_realtime_parking_is_not_static_faq():
    r=route_question("现在停车场还有车位吗？")
    assert r["action"]=="human_escalation" and r["realtime_data_required"]

def test_transaction_is_handoff_only():
    assert route_question("帮我取消订单")["action"]=="transaction_handoff"

def test_safety_has_highest_priority():
    r=route_question("我订单的房间里闻到煤气味")
    assert r["intent"]=="safety_incident" and r["risk_level"]=="critical"

def test_invalid_context_status_rejected():
    try:
        update_order_status(default_context(),"AUTHENTICATED")
        assert False
    except ValueError:
        assert True
