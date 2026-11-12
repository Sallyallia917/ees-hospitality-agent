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
    details = agent.handle_booking_query("企业发票，抬头：某某科技有限公司，税号：91350211M000100Y43，邮箱：test@example.com",
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


def test_repeated_service_request_reuses_existing_active_ticket(tmp_path):
    tickets = TicketService(tmp_path / "tickets.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)

    first_context = {}
    agent.handle_booking_query("空调不制冷", principal=principal(), context=first_context)
    first_prompt = agent.handle_booking_query(
        "第一笔", principal=principal(), context=first_context
    )
    assert first_prompt["status"] == "awaiting_ticket_confirmation"
    created = agent.handle_booking_query(
        "确认", principal=principal(), context=first_context
    )
    assert created["status"] == "ticket_created"
    original_id = created["data"]["ticket"]["ticket_id"]

    repeated_context = {}
    agent.handle_booking_query("空调不制冷", principal=principal(), context=repeated_context)
    repeated = agent.handle_booking_query(
        "第一笔", principal=principal(), context=repeated_context
    )
    assert repeated["status"] == "existing_ticket"
    assert repeated["data"]["reused"] is True
    assert repeated["data"]["ticket"]["ticket_id"] == original_id
    assert len(tickets.list_tickets(guest_id="CUST-001")) == 1


def test_different_issue_types_for_same_booking_can_create_parallel_tickets(tmp_path):
    tickets = TicketService(tmp_path / "tickets.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)

    maintenance_context = {}
    agent.handle_booking_query("空调不制冷", principal=principal(), context=maintenance_context)
    agent.handle_booking_query("第一笔", principal=principal(), context=maintenance_context)
    maintenance = agent.handle_booking_query(
        "确认", principal=principal(), context=maintenance_context
    )
    booking_id = maintenance["data"]["booking_id"]

    complaint_context = {}
    agent.handle_booking_query(
        "房间噪音投诉，影响休息", principal=principal(), context=complaint_context
    )
    prompt = agent.handle_booking_query(
        "第一笔", principal=principal(), context=complaint_context
    )
    assert prompt["status"] == "awaiting_ticket_confirmation"
    complaint = agent.handle_booking_query(
        "确认", principal=principal(), context=complaint_context
    )

    assert complaint["status"] == "ticket_created"
    rows = tickets.list_tickets(guest_id="CUST-001")
    same_booking = [row for row in rows if row["booking_id"] == booking_id]
    assert len(same_booking) == 2
    assert {row["issue_type"] for row in same_booking} == {
        "ROOM_MAINTENANCE", "NOISE"
    }


def test_service_ticket_operation_id_is_stable_during_confirmation_dialogue(tmp_path):
    tickets = TicketService(tmp_path / "tickets.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    agent.handle_booking_query("空调不制冷", principal=principal(), context=context)
    agent.handle_booking_query("第一笔", principal=principal(), context=context)
    operation_id = context["pending_ticket_request"]["operation_id"]

    supplemented = agent.handle_booking_query(
        "补充：已经影响正常休息", principal=principal(), context=context
    )
    assert supplemented["status"] == "awaiting_ticket_confirmation"
    assert context["pending_ticket_request"]["operation_id"] == operation_id


def test_guest_can_query_own_active_ticket_status_only(tmp_path):
    tickets = TicketService(tmp_path / "tickets.sqlite3")
    own = tickets.create_ticket(
        "CUST-001", "空调维修", "MAINTENANCE", booking_id="DEMO-BOOKING-2001"
    )
    tickets.create_ticket(
        "CUST-002", "房间清洁", "CLEANING", booking_id="DEMO-BOOKING-2002"
    )
    agent = ConversationOrchestrator(BookingService(), tickets)

    result = agent.handle_booking_query(
        "我的工单状态", principal=principal(), context={}
    )
    assert result["status"] == "active_tickets_found"
    assert len(result["data"]["tickets"]) == 1
    assert result["data"]["tickets"][0]["ticket_id"] == own["ticket"]["ticket_id"]
    assert own["ticket"]["ticket_id"] in result["answer"]


def test_guest_ticket_status_query_with_no_active_tickets_is_explicit(tmp_path):
    tickets = TicketService(tmp_path / "tickets.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    result = agent.handle_booking_query(
        "查一下我的工单进度", principal=principal(), context={}
    )
    assert result["status"] == "no_active_tickets"
    assert result["data"]["tickets"] == []


def test_personal_invoice_details_are_structured_without_tax_id(tmp_path):
    tickets = TicketService(tmp_path / "personal-invoice.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query("开发票", principal=principal(), context=context)
    if first["action"] == "select_booking_for_service_ticket":
        agent.handle_booking_query("第一笔", principal=principal(), context=context)
    result = agent.handle_booking_query(
        "个人发票，抬头：张三", principal=principal(), context=context
    )
    assert result["status"] == "awaiting_ticket_confirmation"
    details = result["data"]["invoice_details"]
    assert details["invoice_type"] == "PERSONAL"
    assert details["title"] == "张三"
    assert "tax_id" not in details

    created = agent.handle_booking_query(
        "确认", principal=principal(), context=context
    )
    assert created["status"] == "ticket_created"
    assert created["data"]["ticket"]["metadata"]["invoice_details"]["invoice_type"] == "PERSONAL"


def test_company_invoice_rejects_invalid_tax_id_before_confirmation(tmp_path):
    tickets = TicketService(tmp_path / "invalid-invoice.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query("开发票", principal=principal(), context=context)
    if first["action"] == "select_booking_for_service_ticket":
        agent.handle_booking_query("第一笔", principal=principal(), context=context)

    invalid = agent.handle_booking_query(
        "企业发票，抬头：某某科技有限公司，税号：123456",
        principal=principal(), context=context,
    )
    assert invalid["status"] == "collecting_invoice_details"
    assert "18 位" in invalid["answer"]
    assert tickets.list_tickets(guest_id="CUST-001") == []

    valid = agent.handle_booking_query(
        "税号：91350211M000100Y43", principal=principal(), context=context
    )
    assert valid["status"] == "awaiting_ticket_confirmation"
    assert valid["data"]["invoice_details"]["tax_id"] == "91350211M000100Y43"


def test_unauthorized_room_entry_bypasses_booking_clarification_and_creates_urgent_ticket(tmp_path):
    tickets = TicketService(tmp_path / "safety.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    result = agent.handle_booking_query(
        "保洁员直接刷卡进来了，我没有允许",
        principal=principal(), context={},
    )
    assert result["status"] == "safety_ticket_created"
    ticket = result["data"]["ticket"]
    assert ticket["issue_type"] == "UNAUTHORIZED_ROOM_ENTRY"
    assert ticket["priority"] == "URGENT"
    assert ticket["status"] == "SUBMITTED"
    assert result["needs_human"] is True
    assert "不会自动呼叫救援" in result["answer"]


def test_safety_incident_gives_immediate_guidance_without_authentication(tmp_path):
    tickets = TicketService(tmp_path / "safety-unauth.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    result = agent.handle_booking_query(
        "房间里闻到煤气味", principal=None, context={},
    )
    assert result["status"] == "safety_handoff_required"
    assert "立即远离危险区域" in result["answer"]
    assert tickets.list_tickets(staff=True) == []


def test_personal_invoice_requires_an_actual_title(tmp_path):
    tickets = TicketService(tmp_path / "personal-title.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query("开发票", principal=principal(), context=context)
    if first["action"] == "select_booking_for_service_ticket":
        agent.handle_booking_query("第一笔", principal=principal(), context=context)

    incomplete = agent.handle_booking_query(
        "个人发票", principal=principal(), context=context
    )
    assert incomplete["status"] == "collecting_invoice_details"
    assert "发票抬头" in incomplete["answer"]
    assert tickets.list_tickets(guest_id="CUST-001") == []

    completed = agent.handle_booking_query(
        "抬头：张三", principal=principal(), context=context
    )
    assert completed["status"] == "awaiting_ticket_confirmation"
    assert completed["data"]["invoice_details"]["title"] == "张三"


def test_invoice_can_switch_from_invalid_company_tax_id_to_personal_invoice(tmp_path):
    tickets = TicketService(tmp_path / "invoice-switch.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query("开发票", principal=principal(), context=context)
    if first["action"] == "select_booking_for_service_ticket":
        agent.handle_booking_query("第一笔", principal=principal(), context=context)

    invalid = agent.handle_booking_query(
        "企业发票，抬头：某某科技有限公司，税号：123456",
        principal=principal(), context=context,
    )
    assert invalid["status"] == "collecting_invoice_details"

    switched = agent.handle_booking_query(
        "改开个人发票，抬头：张三", principal=principal(), context=context
    )
    assert switched["status"] == "awaiting_ticket_confirmation"
    details = switched["data"]["invoice_details"]
    assert details["invoice_type"] == "PERSONAL"
    assert details["title"] == "张三"
    assert "tax_id" not in details
    assert "tax_id_invalid" not in details


def test_repeated_identical_safety_message_is_idempotent_but_new_incident_is_not_suppressed(tmp_path):
    tickets = TicketService(tmp_path / "safety-retry.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query(
        "保洁员未经允许刷卡进入客房", principal=principal(), context=context
    )
    retry = agent.handle_booking_query(
        "保洁员未经允许刷卡进入客房", principal=principal(), context=context
    )
    assert first["data"]["ticket"]["ticket_id"] == retry["data"]["ticket"]["ticket_id"]
    assert len(tickets.list_tickets(guest_id="CUST-001")) == 1

    second_incident = agent.handle_booking_query(
        "今天又有工作人员未经允许进入客房", principal=principal(), context=context
    )
    assert second_incident["status"] == "safety_ticket_created"
    assert len(tickets.list_tickets(guest_id="CUST-001")) == 2


def test_guest_can_cancel_invoice_request_while_collecting_details(tmp_path):
    tickets = TicketService(tmp_path / "invoice-cancel.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query("开发票", principal=principal(), context=context)
    if first["action"] == "select_booking_for_service_ticket":
        agent.handle_booking_query("第一笔", principal=principal(), context=context)
    assert context["pending_action"] == "collect_invoice_details"

    cancelled = agent.handle_booking_query(
        "算了，不开发票了", principal=principal(), context=context
    )
    assert cancelled["status"] == "ticket_cancelled"
    assert context.get("pending_ticket_request") is None
    assert context.get("pending_action") is None
    assert tickets.list_tickets(guest_id="CUST-001") == []


def test_natural_ticket_progress_phrases_route_to_status_lookup():
    for phrase in ("我的工单进展如何", "工单怎么还没处理", "有人接单了吗"):
        result = classify_by_rules(phrase)
        assert result["intent"] == "ticket_status_inquiry"
        assert result["sub_intent"] == "active_ticket_status"
