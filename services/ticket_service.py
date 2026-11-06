"""SQLite-backed service tickets for the EES demonstration.

Synthetic/demo workflow only: no real PMS, CRM, notification or dispatch integration.
"""
from __future__ import annotations
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

STATUSES = {"SUBMITTED", "ASSIGNED", "PROCESSING", "PENDING_USER", "RESOLVED", "CLOSED", "ESCALATED"}
TRANSITIONS = {
    "SUBMITTED": {"ASSIGNED", "PROCESSING", "ESCALATED"},
    "ASSIGNED": {"PROCESSING", "PENDING_USER", "ESCALATED"},
    "PROCESSING": {"PENDING_USER", "RESOLVED", "ESCALATED"},
    "PENDING_USER": {"PROCESSING", "ESCALATED", "CLOSED"},
    "RESOLVED": {"CLOSED", "PROCESSING"},
    "CLOSED": {"PROCESSING"},
    "ESCALATED": {"ASSIGNED", "PROCESSING", "RESOLVED"},
}
CATEGORIES = {"CLEANING", "ROOM_SERVICE", "MAINTENANCE", "COMPLAINT", "BOOKING_ISSUE", "REFUND_REQUEST", "OTHER"}
PRIORITIES = {"LOW", "NORMAL", "HIGH", "URGENT"}

class TicketService:
    def __init__(self, db_path="data/tickets.sqlite3"):
        self.db_path = str(db_path)
        self._memory_connection = None
        if self.db_path == ":memory:":
            self._memory_connection = sqlite3.connect(":memory:")
            self._memory_connection.row_factory = sqlite3.Row
        else:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        if self._memory_connection is not None:
            return self._memory_connection
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY,
                    guest_id TEXT NOT NULL,
                    booking_id TEXT,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    assigned_to TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    history_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    operation_id TEXT
                )
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(tickets)").fetchall()}
            if "metadata_json" not in columns:
                conn.execute("ALTER TABLE tickets ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
            if "operation_id" not in columns:
                conn.execute("ALTER TABLE tickets ADD COLUMN operation_id TEXT")

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def create_ticket(self, guest_id, description, category="OTHER", booking_id=None,
                      priority="NORMAL", idempotency_key=None, metadata=None, operation_id=None):
        if not guest_id or not str(guest_id).strip():
            return {"ok": False, "error": "guest_identity_required"}
        description = str(description or "").strip()
        if not description:
            return {"ok": False, "error": "description_required"}
        category = str(category).upper()
        priority = str(priority).upper()
        if category not in CATEGORIES or priority not in PRIORITIES:
            return {"ok": False, "error": "invalid_category_or_priority"}
        key = str(idempotency_key or uuid.uuid4())
        now = self._now()
        with self._connect() as conn:
            existing = conn.execute("SELECT * FROM tickets WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                return {"ok": True, "created": False, "ticket": self._row(existing)}
            ticket_id = "TKT-" + uuid.uuid4().hex[:10].upper()
            history = [{"status": "SUBMITTED", "at": now, "actor": "guest", "note": "ticket_created"}]
            conn.execute("""INSERT INTO tickets (
                ticket_id, guest_id, booking_id, category, description, priority, status,
                assigned_to, idempotency_key, created_at, updated_at, history_json,
                metadata_json, operation_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ticket_id, str(guest_id), booking_id, category, description, priority,
                 "SUBMITTED", None, key, now, now, json.dumps(history, ensure_ascii=False),
                 json.dumps(metadata or {}, ensure_ascii=False), operation_id))
            row = conn.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            return {"ok": True, "created": True, "ticket": self._row(row)}

    def get_ticket(self, ticket_id, guest_id=None, staff=False):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
        if row is None or (not staff and (not guest_id or row["guest_id"] != str(guest_id))):
            return {"ok": False, "error": "not_found"}
        return {"ok": True, "ticket": self._row(row)}

    def list_tickets(self, guest_id=None, staff=False, limit=100):
        with self._connect() as conn:
            if staff:
                rows = conn.execute("SELECT * FROM tickets ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM tickets WHERE guest_id=? ORDER BY created_at DESC LIMIT ?",
                                    (str(guest_id or ""), int(limit))).fetchall()
        return [self._row(row) for row in rows]

    def update_ticket(self, ticket_id, status, actor, note="", assigned_to=None):
        status = str(status).upper()
        if status not in STATUSES:
            return {"ok": False, "error": "invalid_status"}
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            if row is None:
                return {"ok": False, "error": "not_found"}
            current = row["status"]
            if status not in TRANSITIONS[current]:
                return {"ok": False, "error": "invalid_transition", "current_status": current}
            history = json.loads(row["history_json"])
            history.append({"status": status, "at": self._now(), "actor": str(actor),
                            "note": str(note or ""), "assigned_to": assigned_to})
            conn.execute("""UPDATE tickets SET status=?, assigned_to=COALESCE(?, assigned_to),
                updated_at=?, history_json=? WHERE ticket_id=?""",
                (status, assigned_to, self._now(), json.dumps(history, ensure_ascii=False), ticket_id))
            updated = conn.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            return {"ok": True, "ticket": self._row(updated)}

    @staticmethod
    def _row(row):
        item = dict(row)
        item["history"] = json.loads(item.pop("history_json"))
        item["metadata"] = json.loads(item.pop("metadata_json", "{}") or "{}")
        return item
