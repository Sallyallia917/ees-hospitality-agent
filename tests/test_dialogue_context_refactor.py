from datetime import datetime, timedelta, timezone

from services.identity import Principal
from services.semantic_classifier import classify_by_rules
from services.intent_router import route_question
from services.conversation_orchestrator import ConversationOrchestrator

NOW = datetime.now(timezone.utc)

def principal(customer_id="CUST-001"):
    return Principal(
        principal_id=f"DEMO-PRINCIPAL-{customer_id}",
        customer_id=customer_id,
        auth_method="demo_pin",
        authenticated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=20)).isoformat(),
    )

def test_order_count_is_a_distinct_list_intent():
    result = classify_by_rules("我有几笔订单")
    assert result["intent"] == "booking_list_query"
    assert route_question("我有几笔订单")["action"] == "booking_list"

def test_first_person_booking_fields_do_not_fall_into_public_faq():
    for question in ("我的入住日期是哪天", "我的含早餐吗", "我的停车权益是什么"):
        result = classify_by_rules(question)
        assert result["intent"] == "booking_related_inquiry"

def test_booking_error_routes_to_human_not_rag():
    for question in ("订单订错了", "预定错误", "我的订单信息有误"):
        route = route_question(question)
        assert route["action"] == "service_ticket_request"
        assert route["intent"] == "booking_issue"

def test_public_facility_faq_stays_in_rag():
    for question in ("酒店有停车场吗", "早餐几点开始", "入住时间是什么"):
        assert route_question(question)["action"] == "rag_answer"

def test_active_booking_context_resolves_first_person_followup_without_marker():
    context = {}
    orchestrator = ConversationOrchestrator()
    first = orchestrator.handle_booking_query(
        "DEMO-BOOKING-2001 什么房型？", principal=principal("CUST-002"),
        context=context
    )
    followup = orchestrator.handle_booking_query(
        "我的入住日期是哪天", principal=principal("CUST-002"),
        history=[{"intent": "booking_related_inquiry"}], context=context
    )
    assert first["status"] in ("ok", "data_incomplete")
    assert followup["status"] in ("ok", "data_incomplete")
    assert followup["data"]["booking"]["booking_id"] == "DEMO-BOOKING-2001"
    assert "入住日期" in followup["answer"]

def test_list_then_second_booking_selection_is_stateful_and_authorized():
    context = {}
    orchestrator = ConversationOrchestrator()
    listing = orchestrator.handle_booking_query(
        "我有几笔订单", principal=principal("CUST-001"), context=context
    )
    assert listing["status"] == "needs_clarification"
    assert len(context["candidate_booking_ids"]) >= 2

    selected = orchestrator.handle_booking_query(
        "第二笔", principal=principal("CUST-001"),
        history=[{"intent": "booking_list_query"}], context=context
    )
    assert selected["status"] in ("ok", "data_incomplete")
    assert selected["data"]["booking"]["booking_id"] == context["active_booking_id"]
    assert context["candidate_booking_ids"] == []

def test_list_query_still_requires_authenticated_principal():
    result = ConversationOrchestrator().handle_booking_query("我有几笔订单")
    assert result["status"] == "unauthenticated"
    assert result["data"] is None
