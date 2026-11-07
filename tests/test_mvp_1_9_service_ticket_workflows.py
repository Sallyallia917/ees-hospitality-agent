from datetime import datetime, timedelta, timezone

from services.identity import Principal
from services.booking_service import BookingService
from services.conversation_orchestrator import ConversationOrchestrator
from services.semantic_classifier import classify_by_rules
from services.ticket_service import TicketService


NOW = datetime.now(timezone.utc)


def principal():
    return Principal(
        principal_id="DEMO-PRINCIPAL-CUST-001",
        customer_id="CUST-001",
        auth_method="demo_pin",
        authenticated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=20)).isoformat(),
    )


def test_service_and_complaint_intents_are_distinguished():
    assert classify_by_rules("空调不制冷")["intent"] == "service_request"
    assert classify_by_rules("环境脏乱差")["intent"] == "complaint"
    assert classify_by_rules("房间吵")["intent"] == "complaint"
    assert classify_by_rules("开发票")["intent"] == "invoice_request"
    assert classify_by_rules("有没有电梯")["intent"] == "public_knowledge_inquiry"
    facility = classify_by_rules("没有电梯")
    assert facility["intent"] == "service_request"
    assert facility["sub_intent"] == "facility_or_complaint_clarification"


def test_legacy_categories_normalize_to_mece_primary_categories(tmp_path):
    service = TicketService(tmp_path / "tickets.sqlite3")
    expected = {
        "REFUND_REQUEST": ("TRANSACTION_ORDER", "CANCELLATION_REFUND"),
        "BOOKING_ISSUE": ("TRANSACTION_ORDER", "BOOKING_ERROR"),
        "CLEANING": ("STAY_SERVICE", "ROOM_CLEANING"),
        "MAINTENANCE": ("STAY_SERVICE", "ROOM_MAINTENANCE"),
        "ROOM_SERVICE": ("STAY_SERVICE", "ROOM_AMENITY"),
        "COMPLAINT": ("COMPLAINT_EXPERIENCE", "SERVICE_COMPLAINT"),
        "OTHER": ("CONSULTATION_OTHER", "OTHER"),
    }
    for old_category, (category, issue_type) in expected.items():
        result = service.create_ticket(
            "guest-1", f"legacy {old_category}", old_category,
            idempotency_key=f"legacy-{old_category}"
        )
        assert result["ok"]
        assert result["ticket"]["category"] == category
        assert result["ticket"]["metadata"]["issue_type"] == issue_type


def test_service_request_creates_ticket_only_after_confirmation(tmp_path):
    tickets = TicketService(tmp_path / "tickets.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query("空调不制冷", principal=principal(), context=context)
    assert first["status"] == "needs_clarification"
    selected = agent.handle_booking_query("第一笔", principal=principal(), context=context)
    assert selected["status"] == "awaiting_ticket_confirmation"
    assert tickets.list_tickets(guest_id="CUST-001") == []
    created = agent.handle_booking_query("确认", principal=principal(), context=context)
    assert created["status"] == "ticket_created"
    assert created["data"]["ticket"]["category"] == "STAY_SERVICE"
    assert created["data"]["ticket"]["metadata"]["issue_type"] == "ROOM_MAINTENANCE"
    assert len(tickets.list_tickets(guest_id="CUST-001")) == 1


def test_invoice_ticket_collects_details_before_confirmation(tmp_path):
    tickets = TicketService(tmp_path / "tickets.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query("开发票", principal=principal(), context=context)
    if first["action"] == "select_booking_for_service_ticket":
        agent.handle_booking_query("第一笔", principal=principal(), context=context)
    assert context["pending_action"] == "collect_invoice_details"
    details = agent.handle_booking_query("某某科技有限公司，税号 123456，发送邮箱 test@example.com",
                                         principal=principal(), context=context)
    assert details["status"] == "awaiting_ticket_confirmation"
    assert tickets.list_tickets(guest_id="CUST-001") == []
    created = agent.handle_booking_query("确认", principal=principal(), context=context)
    assert created["status"] == "ticket_created"
    assert created["data"]["ticket"]["category"] == "BILLING_DOCUMENT"
    assert created["data"]["ticket"]["metadata"]["invoice_details"]


def test_facility_statement_is_clarified_then_routed_as_experience_complaint():
    agent = ConversationOrchestrator(BookingService(), TicketService(":memory:"))
    context = {}
    first = agent.handle_booking_query("没有电梯", context=context)
    assert first["status"] == "needs_clarification"
    assert context["pending_action"] == "clarify_facility_context"
    second = agent.handle_booking_query("已经入住，很不方便，希望反馈", principal=principal(), context=context)
    assert second["status"] == "needs_clarification"
    assert context["pending_ticket_request"]["issue_type"] == "FACILITY_COMPLAINT"
