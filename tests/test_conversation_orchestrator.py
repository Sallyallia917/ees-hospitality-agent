from datetime import datetime, timedelta, timezone
from services.identity import Principal
from services.conversation_orchestrator import ConversationOrchestrator

NOW = datetime.now(timezone.utc)

def principal(customer_id="CUST-002"):
    return Principal(
        principal_id=f"DEMO-PRINCIPAL-{customer_id}", customer_id=customer_id,
        auth_method="demo_pin", authenticated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=20)).isoformat(),
    )

def test_booking_reference_routes_to_lookup():
    from services.intent_router import route_question
    assert route_question("DEMO-BOOKING-2001 什么房型？")["action"] == "booking_lookup"

def test_login_required_before_lookup():
    result = ConversationOrchestrator().handle_booking_query("DEMO-BOOKING-2001 什么房型？")
    assert result["status"] == "unauthenticated" and result["data"] is None

def test_owner_can_query_and_get_grounded_answer():
    result = ConversationOrchestrator().handle_booking_query("DEMO-BOOKING-2001 什么房型？", principal=principal())
    assert result["status"] in ("ok", "data_incomplete")
    assert result["data"]["booking"]["booking_id"] == "DEMO-BOOKING-2001"
    assert result["data"]["booking"]["room_type"] and result["answer"]

def test_other_customer_booking_is_not_disclosed():
    result = ConversationOrchestrator().handle_booking_query("DEMO-BOOKING-1001 什么房型？", principal=principal())
    assert result["status"] == "not_found" and result["data"] is None
    assert "没有找到您有权查看" in result["answer"]

def test_multiple_owned_orders_require_clarification():
    result = ConversationOrchestrator().handle_booking_query("我预订的是什么房型？", principal=principal("CUST-001"))
    assert result["status"] == "needs_clarification"
    assert result["needs_clarification"] and len(result["data"]["matched_bookings"]) <= 3

def test_followup_uses_only_authorized_active_booking():
    context, orchestrator = {}, ConversationOrchestrator()
    first = orchestrator.handle_booking_query("DEMO-BOOKING-2001 什么房型？", principal=principal(), context=context)
    second = orchestrator.handle_booking_query("那早餐包含吗？", principal=principal(), history=[{"intent":"booking_related_inquiry"}], context=context)
    assert first["status"] in ("ok", "data_incomplete")
    assert second["status"] in ("ok", "data_incomplete")
    assert second["data"]["booking"]["booking_id"] == "DEMO-BOOKING-2001"
