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


def test_natural_language_refund_and_maintenance_progress_queries_are_classified():
    assert classify_by_rules("我的退款啥进度了")["sub_intent"] == "refund_status"
    assert classify_by_rules("我的订单退款进度如何了")["intent"] == "ticket_status_inquiry"
    assert classify_by_rules("空调还没人来修吗")["sub_intent"] == "maintenance_status"
    assert classify_by_rules("发票开好了吗")["sub_intent"] == "invoice_status"


def test_ticket_status_query_filters_by_business_issue_type(tmp_path):
    tickets = TicketService(tmp_path / "ticket-status-filter.sqlite3")
    refund = tickets.create_ticket(
        "CUST-001", "退款申请", "REFUND_REQUEST",
        booking_id="DEMO-BOOKING-2001",
    )
    maintenance = tickets.create_ticket(
        "CUST-001", "空调维修", "MAINTENANCE",
        booking_id="DEMO-BOOKING-2001",
    )
    agent = ConversationOrchestrator(BookingService(), tickets)

    refund_result = agent.handle_booking_query(
        "我的退款啥进度了", principal=principal(), context={},
    )
    assert refund_result["status"] == "active_tickets_found"
    assert [x["ticket_id"] for x in refund_result["data"]["tickets"]] == [
        refund["ticket"]["ticket_id"]
    ]

    maintenance_result = agent.handle_booking_query(
        "空调还没人来修吗", principal=principal(), context={},
    )
    assert maintenance_result["status"] == "active_tickets_found"
    assert [x["ticket_id"] for x in maintenance_result["data"]["tickets"]] == [
        maintenance["ticket"]["ticket_id"]
    ]


def test_guest_can_append_note_to_recent_active_ticket_without_new_ticket(tmp_path):
    tickets = TicketService(tmp_path / "ticket-note.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}

    first = agent.handle_booking_query(
        "空调不制冷", principal=principal(), context=context,
    )
    if first["action"] == "select_booking_for_service_ticket":
        agent.handle_booking_query("第一笔", principal=principal(), context=context)
    created = agent.handle_booking_query(
        "确认", principal=principal(), context=context,
    )
    ticket_id = created["data"]["ticket"]["ticket_id"]

    prompt = agent.handle_booking_query(
        "再次反馈", principal=principal(), context=context,
    )
    assert prompt["status"] == "needs_clarification"
    assert context["pending_action"] == "collect_ticket_note"

    appended = agent.handle_booking_query(
        "空调还是不制冷，已经影响休息", principal=principal(), context=context,
    )
    assert appended["status"] == "ticket_note_added"
    assert appended["data"]["ticket"]["ticket_id"] == ticket_id
    assert appended["data"]["ticket"]["status"] == "SUBMITTED"
    history = appended["data"]["ticket"]["history"]
    assert any(
        item.get("event") == "GUEST_NOTE_ADDED"
        and "影响休息" in item.get("note", "")
        for item in history
    )
    assert len(tickets.list_tickets(guest_id="CUST-001")) == 1


def test_append_ticket_note_rejects_non_owner_and_terminal_ticket(tmp_path):
    tickets = TicketService(tmp_path / "ticket-note-boundaries.sqlite3")
    created = tickets.create_ticket(
        "CUST-001", "空调维修", "MAINTENANCE",
        booking_id="DEMO-BOOKING-2001",
    )
    ticket_id = created["ticket"]["ticket_id"]

    unauthorized = tickets.append_ticket_note(ticket_id, "CUST-002", "补充内容")
    assert unauthorized == {"ok": False, "error": "not_found"}

    resolved = tickets.update_ticket(
        ticket_id, "CANCELLED", actor="staff", note="结束工单"
    )
    assert resolved["ok"]
    terminal = tickets.append_ticket_note(ticket_id, "CUST-001", "再次补充")
    assert terminal["ok"] is False
    assert terminal["error"] == "ticket_not_active"


def test_personal_invoice_accepts_bare_name_during_detail_collection(tmp_path):
    tickets = TicketService(tmp_path / "personal-invoice-bare-name.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query(
        "开发票", principal=principal(), context=context,
    )
    if first["action"] == "select_booking_for_service_ticket":
        agent.handle_booking_query("第一笔", principal=principal(), context=context)
    selected_type = agent.handle_booking_query(
        "个人发票", principal=principal(), context=context,
    )
    assert selected_type["status"] == "collecting_invoice_details"
    name = agent.handle_booking_query(
        "张三", principal=principal(), context=context,
    )
    assert name["status"] == "awaiting_ticket_confirmation"
    assert name["data"]["invoice_details"]["title"] == "张三"


def test_privacy_intrusion_and_direct_room_entry_are_safety_incidents():
    for phrase in ("保洁员直接进我房间了", "保洁员侵犯我的隐私"):
        result = classify_by_rules(phrase)
        assert result["intent"] == "safety_incident"
        assert result["sub_intent"] == "unauthorized_entry"


def test_guest_can_withdraw_submitted_cancellation_request_without_changing_booking(tmp_path):
    tickets = TicketService(tmp_path / "withdraw-cancel.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}

    prompt = agent.handle_booking_query(
        "我要取消订单", principal=principal(), context=context,
    )
    if prompt.get("action") == "select_booking_for_transaction":
        prompt = agent.handle_booking_query(
            "第一笔", principal=principal(), context=context,
        )
    assert prompt["status"] == "awaiting_confirmation"
    created = agent.handle_booking_query(
        "确认", principal=principal(), context=context,
    )
    assert created["status"] == "ticket_created"
    ticket_id = created["data"]["ticket"]["ticket_id"]

    withdrawn = agent.handle_booking_query(
        "不取消了，要正常入住", principal=principal(), context=context,
    )
    assert withdrawn["status"] == "request_withdrawn"
    assert withdrawn["data"]["ticket"]["ticket_id"] == ticket_id
    assert withdrawn["data"]["ticket"]["status"] == "CANCELLED"
    assert "不会修改真实订单状态" in withdrawn["answer"]


def test_guest_withdrawal_after_assignment_requires_human_review(tmp_path):
    tickets = TicketService(tmp_path / "withdraw-assigned.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}

    prompt = agent.handle_booking_query("我要取消订单", principal=principal(), context=context)
    if prompt.get("action") == "select_booking_for_transaction":
        prompt = agent.handle_booking_query("第一笔", principal=principal(), context=context)
    created = agent.handle_booking_query("确认", principal=principal(), context=context)
    ticket_id = created["data"]["ticket"]["ticket_id"]
    assigned = tickets.update_ticket(ticket_id, "ASSIGNED", actor="staff")
    assert assigned["ok"]

    result = agent.handle_booking_query(
        "不取消了，要正常入住", principal=principal(), context=context,
    )
    assert result["status"] == "withdrawal_requires_human"
    assert result["data"]["ticket_id"] == ticket_id
    assert tickets.get_ticket(ticket_id, guest_id="CUST-001")["ticket"]["status"] == "ASSIGNED"


def test_trip_change_language_is_clarified_instead_of_sent_to_rag_or_refund():
    for phrase in ("计划有变，去不了了", "行程有变，住不了了"):
        result = classify_by_rules(phrase)
        assert result["intent"] == "transaction_request"
        assert result["sub_intent"] == "clarify_trip_change"


def test_trip_change_clarification_separates_cancel_from_reschedule(tmp_path):
    agent = ConversationOrchestrator(
        BookingService(), TicketService(tmp_path / "trip-change.sqlite3")
    )
    context = {}
    first = agent.handle_booking_query(
        "计划有变，去不了了", principal=principal(), context=context
    )
    assert first["status"] == "needs_clarification"
    assert context["pending_action"] == "clarify_trip_change"

    cancel = agent.handle_booking_query(
        "取消订单，申请退款", principal=principal(), context=context
    )
    assert cancel["status"] == "awaiting_confirmation"
    assert context["pending_action"] == "confirm_transaction"


def test_free_cancellation_phrase_confirms_only_in_transaction_confirmation_context():
    context = {"pending_action": "confirm_transaction"}
    result = classify_by_rules("免费取消", context=context)
    assert result["intent"] == "transaction_request"
    assert result["sub_intent"] == "confirm_transaction"

    outside = classify_by_rules("免费取消", context={})
    assert outside["intent"] != "transaction_request" or outside["sub_intent"] != "confirm_transaction"


def test_merchant_unable_to_fulfill_creates_complaint_ticket_after_confirmation(tmp_path):
    tickets = TicketService(tmp_path / "merchant-fulfillment.sqlite3")
    agent = ConversationOrchestrator(BookingService(), tickets)
    context = {}
    first = agent.handle_booking_query(
        "商家没房接待了", principal=principal(), context=context
    )
    if first["action"] == "select_booking_for_service_ticket":
        first = agent.handle_booking_query(
            "第一笔", principal=principal(), context=context
        )
    assert first["status"] == "awaiting_ticket_confirmation"
    assert first["data"]["issue_type"] == "MERCHANT_COMPLAINT"
    assert tickets.list_tickets(guest_id="CUST-001") == []

    created = agent.handle_booking_query(
        "确认", principal=principal(), context=context
    )
    assert created["status"] == "ticket_created"
    assert created["data"]["ticket"]["issue_type"] == "MERCHANT_COMPLAINT"
    assert created["needs_human"] is True


def test_ticket_progress_lookup_includes_terminal_statuses(tmp_path):
    tickets = TicketService(tmp_path / "terminal-ticket-status.sqlite3")
    created = tickets.create_ticket(
        "CUST-001", "空调维修", "MAINTENANCE",
        booking_id="DEMO-BOOKING-2001",
    )
    ticket_id = created["ticket"]["ticket_id"]
    closed = tickets.update_ticket(ticket_id, "CANCELLED", actor="staff", note="已取消")
    assert closed["ok"]

    agent = ConversationOrchestrator(BookingService(), tickets)
    result = agent.handle_booking_query(
        "空调维修进度如何", principal=principal(), context={}
    )
    assert result["status"] == "active_tickets_found"
    assert result["data"]["tickets"][0]["status"] == "CANCELLED"
    assert "已取消" in result["answer"]


def test_privacy_infringement_is_safety_but_not_mislabelled_room_entry():
    result = classify_by_rules("保洁员侵犯我的隐私")
    assert result["intent"] == "safety_incident"
    assert result["sub_intent"] == "safety"


def test_explicit_reschedule_after_trip_change_clarification_hands_off(tmp_path):
    agent = ConversationOrchestrator(
        BookingService(), TicketService(tmp_path / "reschedule-handoff.sqlite3")
    )
    context = {}
    agent.handle_booking_query(
        "行程有变，住不了了", principal=principal(), context=context
    )
    result = agent.handle_booking_query(
        "我想改期", principal=principal(), context=context
    )
    assert result["status"] == "booking_change_handoff"
    assert result["needs_human"] is True
    assert "不连接 PMS" in result["answer"]
    assert tickets_count := agent.ticket_service.list_tickets(guest_id="CUST-001")
    assert tickets_count == []
