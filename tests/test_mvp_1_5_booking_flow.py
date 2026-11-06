from datetime import datetime, timedelta, timezone

from services.identity import Principal
from services.semantic_classifier import classify_by_rules
from services.intent_router import route_question
from services.conversation_orchestrator import ConversationOrchestrator
from services.ticket_service import TicketService

NOW = datetime.now(timezone.utc)

def principal(customer_id="CUST-001"):
    return Principal(
        principal_id=f"DEMO-PRINCIPAL-{customer_id}",
        customer_id=customer_id,
        auth_method="demo_pin",
        authenticated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=20)).isoformat(),
    )

def test_cancellation_policy_is_distinct_from_cancel_execution():
    assert classify_by_rules("我的高级双床房能取消吗")["intent"] == "cancellation_policy_inquiry"
    assert classify_by_rules("订单的取消政策")["intent"] == "cancellation_policy_inquiry"
    assert classify_by_rules("我要取消我预定的房源")["intent"] == "transaction_request"
    assert route_question("取消退款")["action"] == "transaction_handoff"

def test_policy_query_returns_policy_not_unrelated_booking_fields():
    context = {}
    agent = ConversationOrchestrator()
    result = agent.handle_booking_query(
        "订单的取消政策", principal=principal(), context=context
    )
    assert result["handled"] is True
    assert result["action"] == "select_booking_for_policy"
    selected = agent.handle_booking_query(
        "高级双床房", principal=principal(),
        history=[{"intent": "cancellation_policy_inquiry"}], context=context
    )
    assert selected["action"] == "booking_policy_lookup"
    assert "取消政策" in selected["answer"] or "取消" in selected["answer"]
    assert "超过72小时" in selected["answer"]

def test_cancel_request_requires_order_selection_and_explicit_confirmation():
    context = {}
    agent = ConversationOrchestrator()
    first = agent.handle_booking_query("我要取消我预定的房源", principal=principal(), context=context)
    assert first["status"] == "needs_clarification"
    assert context["pending_action"] == "select_transaction"
    selected = agent.handle_booking_query(
        "高级双床房", principal=principal(),
        history=[{"intent": "transaction_request"}], context=context
    )
    assert selected["status"] == "awaiting_confirmation"
    assert context["pending_action"] == "confirm_transaction"
    confirmed = agent.handle_booking_query(
        "确认", principal=principal(),
        history=[{"intent": "transaction_request"}], context=context
    )
    assert confirmed["status"] == "ticket_created"
    assert confirmed["needs_human"] is True
    assert confirmed["data"]["ticket"]["category"] == "REFUND_REQUEST"
    assert confirmed["data"]["ticket"]["booking_id"] == selected["data"]["booking"]["booking_id"]
    assert "尚未执行取消或退款" in confirmed["answer"]

def test_booking_issue_asks_order_then_issue_details():
    context = {}
    agent = ConversationOrchestrator()
    first = agent.handle_booking_query("订单订错了", principal=principal(), context=context)
    assert first["status"] == "needs_clarification"
    selected = agent.handle_booking_query(
        "高级双床房", principal=principal(),
        history=[{"intent": "booking_issue"}], context=context
    )
    assert selected["status"] == "awaiting_issue_details"
    final = agent.handle_booking_query(
        "入住日期写错了", principal=principal(),
        history=[{"intent": "booking_issue"}], context=context
    )
    assert final["status"] == "human_handoff"
    assert final["needs_human"] is True

def test_candidate_selection_rejects_ambiguous_property_match():
    context = {}
    agent = ConversationOrchestrator()
    agent.handle_booking_query("我有几笔订单", principal=principal(), context=context)
    result = agent.handle_booking_query(
        "双床房", principal=principal(),
        history=[{"intent": "booking_list_query"}], context=context
    )
    assert result["status"] == "needs_clarification"


def test_refund_confirmation_automatically_creates_conversation_ticket(tmp_path):
    from services.booking_service import BookingService
    tickets = TicketService(tmp_path / "tickets.sqlite3")
    agent = ConversationOrchestrator(booking_service=BookingService(), ticket_service=tickets)
    context = {}
    first = agent.handle_booking_query("我要给订错的订单申请退款", principal=principal(), context=context)
    assert first["status"] == "needs_clarification"
    selected = agent.handle_booking_query("高级双床房", principal=principal(), history=[{"intent": "transaction_request"}], context=context)
    assert selected["status"] == "awaiting_confirmation"
    confirmed = agent.handle_booking_query("确认退款", principal=principal(), history=[{"intent": "transaction_request"}], context=context)
    assert confirmed["status"] == "ticket_created"
    ticket = confirmed["data"]["ticket"]
    assert ticket["category"] == "REFUND_REQUEST"
    assert ticket["booking_id"] == selected["data"]["booking"]["booking_id"]
    assert ticket["metadata"]["source"] == "ai_conversation"
    assert ticket["metadata"]["user_confirmed"] is True
    assert ticket["metadata"]["execution_boundary"] == "ticket_only_no_refund_execution"
    assert len(tickets.list_tickets(guest_id="CUST-001")) == 1


def test_refund_ticket_is_not_created_before_user_confirmation(tmp_path):
    from services.booking_service import BookingService
    tickets = TicketService(tmp_path / "tickets.sqlite3")
    agent = ConversationOrchestrator(booking_service=BookingService(), ticket_service=tickets)
    context = {}
    agent.handle_booking_query("我要退款", principal=principal(), context=context)
    agent.handle_booking_query("高级双床房", principal=principal(), history=[{"intent": "transaction_request"}], context=context)
    assert tickets.list_tickets(guest_id="CUST-001") == []
    agent.handle_booking_query("算了", principal=principal(), history=[{"intent": "transaction_request"}], context=context)
    assert tickets.list_tickets(guest_id="CUST-001") == []
