import json
import sqlite3
import threading

import pytest

from services.ticket_service import TicketService


def test_issue_type_is_persisted_as_authoritative_column(tmp_path):
    service = TicketService(tmp_path / "tickets.sqlite3")
    result = service.create_ticket(
        "guest-1", "空调不制冷", "MAINTENANCE", booking_id="B-1"
    )
    assert result["ok"] is True
    assert result["ticket"]["issue_type"] == "ROOM_MAINTENANCE"
    assert result["ticket"]["metadata"]["issue_type"] == "ROOM_MAINTENANCE"


def test_same_booking_and_issue_type_returns_existing_active_ticket(tmp_path):
    service = TicketService(tmp_path / "tickets.sqlite3")
    first = service.create_ticket(
        "guest-1", "空调不制冷", "MAINTENANCE", booking_id="B-1",
        idempotency_key="request-1",
    )
    second = service.create_ticket(
        "guest-1", "空调仍然不制冷", "MAINTENANCE", booking_id="B-1",
        idempotency_key="request-2",
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["deduplicated_by"] == "booking_issue"
    assert second["ticket"]["ticket_id"] == first["ticket"]["ticket_id"]


def test_same_booking_different_issue_types_can_run_in_parallel(tmp_path):
    service = TicketService(tmp_path / "tickets.sqlite3")
    maintenance = service.create_ticket(
        "guest-1", "空调不制冷", "MAINTENANCE", booking_id="B-1"
    )
    cleaning = service.create_ticket(
        "guest-1", "需要清洁", "CLEANING", booking_id="B-1"
    )
    assert maintenance["created"] and cleaning["created"]
    assert maintenance["ticket"]["ticket_id"] != cleaning["ticket"]["ticket_id"]


@pytest.mark.parametrize("terminal_status", ["RESOLVED", "CANCELLED", "CLOSED"])
def test_terminal_ticket_releases_business_deduplication(tmp_path, terminal_status):
    service = TicketService(tmp_path / "tickets.sqlite3")
    first = service.create_ticket(
        "guest-1", "空调维修", "MAINTENANCE", booking_id="B-1"
    )
    ticket_id = first["ticket"]["ticket_id"]
    if terminal_status == "RESOLVED":
        service.update_ticket(ticket_id, "PROCESSING", "staff")
        service.update_ticket(ticket_id, "RESOLVED", "staff")
    elif terminal_status == "CLOSED":
        service.update_ticket(ticket_id, "ASSIGNED", "staff")
        service.update_ticket(ticket_id, "PROCESSING", "staff")
        service.update_ticket(ticket_id, "PENDING_USER", "staff")
        service.update_ticket(ticket_id, "CLOSED", "staff")
    else:
        service.update_ticket(ticket_id, terminal_status, "staff")
    second = service.create_ticket(
        "guest-1", "再次申请空调维修", "MAINTENANCE", booking_id="B-1",
        idempotency_key="new-request",
    )
    assert second["created"] is True
    assert second["ticket"]["ticket_id"] != ticket_id


@pytest.mark.parametrize("terminal_status", ["RESOLVED", "CANCELLED", "CLOSED"])
def test_terminal_status_cannot_be_reopened(tmp_path, terminal_status):
    service = TicketService(tmp_path / "tickets.sqlite3")
    created = service.create_ticket("guest-1", "测试工单", "OTHER")
    ticket_id = created["ticket"]["ticket_id"]
    if terminal_status == "RESOLVED":
        service.update_ticket(ticket_id, "PROCESSING", "staff")
    elif terminal_status == "CLOSED":
        service.update_ticket(ticket_id, "ASSIGNED", "staff")
        service.update_ticket(ticket_id, "PROCESSING", "staff")
        service.update_ticket(ticket_id, "PENDING_USER", "staff")
    result = service.update_ticket(ticket_id, terminal_status, "staff")
    assert result["ok"] is True
    reopened = service.update_ticket(ticket_id, "PROCESSING", "staff")
    assert reopened["ok"] is False
    assert reopened["error"] == "invalid_transition"


def test_escalated_ticket_remains_active_for_deduplication(tmp_path):
    service = TicketService(tmp_path / "tickets.sqlite3")
    first = service.create_ticket(
        "guest-1", "保洁员未经允许进入房间", "COMPLAINT",
        booking_id="B-1", metadata={"issue_type": "UNAUTHORIZED_ROOM_ENTRY"},
    )
    ticket_id = first["ticket"]["ticket_id"]
    service.update_ticket(ticket_id, "ESCALATED", "system")
    duplicate = service.create_ticket(
        "guest-1", "未经允许进入客房", "COMPLAINT", booking_id="B-1",
        metadata={"issue_type": "UNAUTHORIZED_ROOM_ENTRY"},
        idempotency_key="different-operation",
    )
    assert duplicate["created"] is False
    assert duplicate["ticket"]["ticket_id"] == ticket_id


def test_unauthorized_room_entry_is_valid_issue_type(tmp_path):
    service = TicketService(tmp_path / "tickets.sqlite3")
    result = service.create_ticket(
        "guest-1", "保洁员刷卡进入客房", "COMPLAINT",
        metadata={"issue_type": "UNAUTHORIZED_ROOM_ENTRY"},
    )
    assert result["ok"] is True
    assert result["ticket"]["issue_type"] == "UNAUTHORIZED_ROOM_ENTRY"


def test_migration_backfills_issue_type_without_losing_legacy_data(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE tickets (
            ticket_id TEXT PRIMARY KEY, guest_id TEXT NOT NULL, booking_id TEXT,
            category TEXT NOT NULL, description TEXT NOT NULL, priority TEXT NOT NULL,
            status TEXT NOT NULL, assigned_to TEXT, idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, history_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}', operation_id TEXT
        )
    """)
    history = '[{"status":"SUBMITTED","at":"2026-01-01T00:00:00+00:00"}]'
    metadata = json.dumps({"issue_type": "ROOM_MAINTENANCE"}, ensure_ascii=False)
    conn.execute("""
        INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        "TKT-LEGACY", "guest-1", "B-LEGACY", "STAY_SERVICE", "空调故障",
        "NORMAL", "SUBMITTED", None, "legacy-key", "2026-01-01", "2026-01-01",
        history, metadata, None,
    ))
    conn.commit()
    conn.close()

    service = TicketService(path)
    loaded = service.get_ticket("TKT-LEGACY", guest_id="guest-1")
    assert loaded["ok"] is True
    assert loaded["ticket"]["issue_type"] == "ROOM_MAINTENANCE"
    assert loaded["ticket"]["history"] == json.loads(history)
    assert loaded["ticket"]["description"] == "空调故障"
    # Re-initialization is idempotent.
    service_again = TicketService(path)
    assert service_again.get_ticket("TKT-LEGACY", guest_id="guest-1")["ok"]


def test_migration_fails_safely_on_legacy_active_duplicates(tmp_path):
    path = tmp_path / "duplicate-legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE tickets (
            ticket_id TEXT PRIMARY KEY, guest_id TEXT NOT NULL, booking_id TEXT,
            category TEXT NOT NULL, description TEXT NOT NULL, priority TEXT NOT NULL,
            status TEXT NOT NULL, assigned_to TEXT, idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, history_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}', operation_id TEXT
        )
    """)
    for suffix in ("1", "2"):
        conn.execute("""
            INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            f"TKT-{suffix}", "guest-1", "B-DUP", "STAY_SERVICE", "空调故障",
            "NORMAL", "SUBMITTED", None, f"key-{suffix}", "2026-01-01",
            "2026-01-01", "[]", '{"issue_type":"ROOM_MAINTENANCE"}', None,
        ))
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="legacy duplicates"):
        TicketService(path)


def test_concurrent_same_booking_issue_creates_only_one_active_ticket(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    TicketService(path)
    barrier = threading.Barrier(2)
    results = []

    def create(key):
        service = TicketService(path)
        barrier.wait()
        results.append(service.create_ticket(
            "guest-1", "空调故障", "MAINTENANCE",
            booking_id="B-CONCURRENT", idempotency_key=key,
        ))

    threads = [
        threading.Thread(target=create, args=("parallel-1",)),
        threading.Thread(target=create, args=("parallel-2",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert sum(result["created"] for result in results) == 1
    assert results[0]["ticket"]["ticket_id"] == results[1]["ticket"]["ticket_id"]
    check = sqlite3.connect(path)
    count = check.execute("""
        SELECT COUNT(*) FROM tickets
        WHERE booking_id='B-CONCURRENT'
          AND issue_type='ROOM_MAINTENANCE'
          AND status IN ('SUBMITTED','ASSIGNED','PROCESSING','PENDING_USER','ESCALATED')
    """).fetchone()[0]
    check.close()
    assert count == 1
