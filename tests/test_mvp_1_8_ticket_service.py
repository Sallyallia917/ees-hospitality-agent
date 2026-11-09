import pytest
from services.ticket_service import TicketService
from services.dialogue_act import classify_dialogue_act

@pytest.fixture
def tickets(tmp_path):
    return TicketService(tmp_path / "tickets.sqlite3")

def test_create_ticket_and_persist_across_instances(tmp_path):
    path = tmp_path / "tickets.sqlite3"
    first = TicketService(path)
    result = first.create_ticket("guest-1", "空调不制冷", "MAINTENANCE", priority="HIGH")
    assert result["ok"] and result["created"]
    second = TicketService(path)
    loaded = second.get_ticket(result["ticket"]["ticket_id"], guest_id="guest-1")
    assert loaded["ok"]
    assert loaded["ticket"]["description"] == "空调不制冷"

def test_idempotency_prevents_duplicate_ticket(tickets):
    one = tickets.create_ticket("guest-1", "需要两条毛巾", "ROOM_SERVICE", idempotency_key="msg-001")
    two = tickets.create_ticket("guest-1", "需要两条毛巾", "ROOM_SERVICE", idempotency_key="msg-001")
    assert one["created"] is True
    assert two["created"] is False
    assert one["ticket"]["ticket_id"] == two["ticket"]["ticket_id"]

def test_guest_cannot_read_another_guests_ticket(tickets):
    created = tickets.create_ticket("guest-a", "房间需要清洁", "CLEANING")
    ticket_id = created["ticket"]["ticket_id"]
    assert tickets.get_ticket(ticket_id, guest_id="guest-b") == {"ok": False, "error": "not_found"}
    assert tickets.get_ticket(ticket_id, staff=True)["ok"]

def test_valid_ticket_lifecycle_and_audit_history(tickets):
    created = tickets.create_ticket("guest-a", "空调故障", "MAINTENANCE")
    ticket_id = created["ticket"]["ticket_id"]
    assigned = tickets.update_ticket(ticket_id, "ASSIGNED", "staff-1", assigned_to="staff-1")
    processing = tickets.update_ticket(ticket_id, "PROCESSING", "staff-1", note="已接单")
    resolved = tickets.update_ticket(ticket_id, "RESOLVED", "staff-1", note="已维修")
    closed = tickets.update_ticket(ticket_id, "CLOSED", "guest-a", note="住客确认")
    assert all(x["ok"] for x in (assigned, processing, resolved, closed))
    assert len(closed["ticket"]["history"]) == 5

def test_illegal_transition_is_rejected(tickets):
    created = tickets.create_ticket("guest-a", "清洁请求", "CLEANING")
    result = tickets.update_ticket(created["ticket"]["ticket_id"], "CLOSED", "staff-1")
    assert result["error"] == "invalid_transition"

def test_resolved_ticket_can_reopen_for_followup(tickets):
    created = tickets.create_ticket("guest-a", "空调维修", "MAINTENANCE")
    ticket_id = created["ticket"]["ticket_id"]
    tickets.update_ticket(ticket_id, "PROCESSING", "staff")
    tickets.update_ticket(ticket_id, "RESOLVED", "staff")
    reopened = tickets.update_ticket(ticket_id, "PROCESSING", "staff", note="住客反馈仍未解决")
    assert reopened["ok"] and reopened["ticket"]["status"] == "PROCESSING"

def test_dialogue_act_history_correction_supplement_and_status():
    assert classify_dialogue_act("你不记得我取消过一次了吗")["act"] == "history_reference"
    assert classify_dialogue_act("不是，我说的是另一笔订单")["act"] == "correction"
    assert classify_dialogue_act("刚才说的房间空调也坏了")["act"] == "supplement"
    assert classify_dialogue_act("现在处理到哪一步了")["act"] == "status_query"
