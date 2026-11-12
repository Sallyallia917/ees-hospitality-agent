"""SQLite-backed service tickets for the EES demonstration.

Synthetic/demo workflow only: no real PMS, CRM, notification or dispatch integration.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

STATUSES = {
    "SUBMITTED", "ASSIGNED", "PROCESSING", "PENDING_USER",
    "RESOLVED", "CANCELLED", "CLOSED", "ESCALATED",
}
ACTIVE_STATUSES = {
    "SUBMITTED", "ASSIGNED", "PROCESSING", "PENDING_USER", "ESCALATED",
}
TERMINAL_STATUSES = {"RESOLVED", "CANCELLED", "CLOSED"}

# Terminal states cannot be reopened. RESOLVED may only be archived as CLOSED.
TRANSITIONS = {
    "SUBMITTED": {"ASSIGNED", "PROCESSING", "ESCALATED", "CANCELLED"},
    "ASSIGNED": {"PROCESSING", "PENDING_USER", "ESCALATED", "CANCELLED"},
    "PROCESSING": {"PENDING_USER", "RESOLVED", "ESCALATED", "CANCELLED"},
    "PENDING_USER": {"PROCESSING", "ESCALATED", "CLOSED", "CANCELLED"},
    "ESCALATED": {"ASSIGNED", "PROCESSING", "RESOLVED", "CANCELLED"},
    "RESOLVED": {"CLOSED"},
    "CANCELLED": set(),
    "CLOSED": set(),
}

# MECE primary categories. Legacy issue labels are normalized for backward compatibility.
CATEGORIES = {
    "TRANSACTION_ORDER", "STAY_SERVICE", "COMPLAINT_EXPERIENCE",
    "BILLING_DOCUMENT", "CONSULTATION_OTHER",
}
LEGACY_CATEGORY_MAP = {
    "REFUND_REQUEST": "TRANSACTION_ORDER", "BOOKING_ISSUE": "TRANSACTION_ORDER",
    "CLEANING": "STAY_SERVICE", "ROOM_SERVICE": "STAY_SERVICE", "MAINTENANCE": "STAY_SERVICE",
    "COMPLAINT": "COMPLAINT_EXPERIENCE", "OTHER": "CONSULTATION_OTHER",
}
ISSUE_TYPES = {
    "BOOKING_ERROR", "CANCELLATION_REFUND", "ROOM_CLEANING", "ROOM_MAINTENANCE",
    "ROOM_AMENITY", "NOISE", "MERCHANT_COMPLAINT", "SERVICE_COMPLAINT",
    "FACILITY_COMPLAINT", "HYGIENE_COMPLAINT", "INVOICE",
    "UNAUTHORIZED_ROOM_ENTRY", "OTHER",
}
LEGACY_ISSUE_TYPE_MAP = {
    "REFUND_REQUEST": "CANCELLATION_REFUND",
    "BOOKING_ISSUE": "BOOKING_ERROR",
    "CLEANING": "ROOM_CLEANING",
    "ROOM_SERVICE": "ROOM_AMENITY",
    "MAINTENANCE": "ROOM_MAINTENANCE",
    "COMPLAINT": "SERVICE_COMPLAINT",
}
PRIORITIES = {"LOW", "NORMAL", "HIGH", "URGENT"}


def normalize_category(category):
    value = str(category or "CONSULTATION_OTHER").strip().upper()
    return LEGACY_CATEGORY_MAP.get(value, value)


def normalize_issue_type(issue_type, fallback="OTHER"):
    value = str(issue_type or fallback).strip().upper()
    value = LEGACY_ISSUE_TYPE_MAP.get(value, value)
    return value if value in ISSUE_TYPES else "OTHER"


class TicketService:
    def __init__(self, db_path="data/tickets.sqlite3"):
        self.db_path = str(db_path)
        self._memory_connection = None
        if self.db_path == ":memory:":
            self._memory_connection = sqlite3.connect(
                ":memory:", timeout=10, check_same_thread=False
            )
            self._memory_connection.row_factory = sqlite3.Row
        else:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        if self._memory_connection is not None:
            return self._memory_connection
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self, write=False) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except Exception:
            if write:
                conn.rollback()
            raise
        finally:
            if self._memory_connection is None:
                conn.close()

    def _init_db(self):
        with self._connection(write=True) as conn:
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
                    operation_id TEXT,
                    issue_type TEXT
                )
            """)
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(tickets)").fetchall()
            }
            if "metadata_json" not in columns:
                conn.execute(
                    "ALTER TABLE tickets ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                )
            if "operation_id" not in columns:
                conn.execute("ALTER TABLE tickets ADD COLUMN operation_id TEXT")
            if "issue_type" not in columns:
                conn.execute("ALTER TABLE tickets ADD COLUMN issue_type TEXT")

            # Backfill the new authoritative column without changing ticket IDs or history.
            rows = conn.execute(
                "SELECT ticket_id, category, metadata_json, issue_type FROM tickets"
            ).fetchall()
            for row in rows:
                if row["issue_type"]:
                    issue_type = normalize_issue_type(row["issue_type"])
                else:
                    try:
                        metadata = json.loads(row["metadata_json"] or "{}")
                    except (TypeError, json.JSONDecodeError):
                        metadata = {}
                    fallback = LEGACY_ISSUE_TYPE_MAP.get(
                        str(row["category"] or "").upper(), "OTHER"
                    )
                    issue_type = normalize_issue_type(metadata.get("issue_type"), fallback)
                conn.execute(
                    "UPDATE tickets SET issue_type=? WHERE ticket_id=?",
                    (issue_type, row["ticket_id"]),
                )

            duplicates = conn.execute("""
                SELECT booking_id, issue_type, COUNT(*) AS total,
                       GROUP_CONCAT(ticket_id, ',') AS ticket_ids
                FROM tickets
                WHERE booking_id IS NOT NULL AND TRIM(booking_id) <> ''
                  AND status IN ('SUBMITTED', 'ASSIGNED', 'PROCESSING',
                                 'PENDING_USER', 'ESCALATED')
                GROUP BY booking_id, issue_type
                HAVING COUNT(*) > 1
            """).fetchall()
            if duplicates:
                details = [
                    {
                        "booking_id": row["booking_id"],
                        "issue_type": row["issue_type"],
                        "ticket_ids": row["ticket_ids"],
                    }
                    for row in duplicates
                ]
                raise RuntimeError(
                    "Cannot enable active-ticket uniqueness; resolve legacy duplicates first: "
                    + json.dumps(details, ensure_ascii=False)
                )

            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_ticket_booking_issue
                ON tickets (booking_id, issue_type)
                WHERE booking_id IS NOT NULL
                  AND TRIM(booking_id) <> ''
                  AND issue_type IS NOT NULL
                  AND status IN ('SUBMITTED', 'ASSIGNED', 'PROCESSING',
                                 'PENDING_USER', 'ESCALATED')
            """)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def create_ticket(
        self, guest_id, description, category="OTHER", booking_id=None,
        priority="NORMAL", idempotency_key=None, metadata=None, operation_id=None,
    ):
        if not guest_id or not str(guest_id).strip():
            return {"ok": False, "error": "guest_identity_required"}
        description = str(description or "").strip()
        if not description:
            return {"ok": False, "error": "description_required"}

        original_category = str(category or "OTHER").strip().upper()
        category = normalize_category(original_category)
        priority = str(priority or "NORMAL").strip().upper()
        metadata = dict(metadata or {})
        inferred_issue_type = LEGACY_ISSUE_TYPE_MAP.get(original_category, "OTHER")
        issue_type = normalize_issue_type(metadata.get("issue_type"), inferred_issue_type)
        metadata["issue_type"] = issue_type
        if category not in CATEGORIES or priority not in PRIORITIES:
            return {"ok": False, "error": "invalid_category_or_priority"}

        normalized_booking_id = (
            str(booking_id).strip() if booking_id is not None and str(booking_id).strip()
            else None
        )
        key = str(idempotency_key or uuid.uuid4())
        now = self._now()

        with self._connection(write=True) as conn:
            existing = conn.execute(
                "SELECT * FROM tickets WHERE idempotency_key=?", (key,)
            ).fetchone()
            if existing:
                return {
                    "ok": True, "created": False, "deduplicated_by": "idempotency_key",
                    "ticket": self._row(existing),
                }

            if normalized_booking_id:
                existing = conn.execute("""
                    SELECT * FROM tickets
                    WHERE booking_id=? AND issue_type=?
                      AND status IN ('SUBMITTED', 'ASSIGNED', 'PROCESSING',
                                     'PENDING_USER', 'ESCALATED')
                    ORDER BY created_at DESC LIMIT 1
                """, (normalized_booking_id, issue_type)).fetchone()
                if existing:
                    return {
                        "ok": True, "created": False, "deduplicated_by": "booking_issue",
                        "ticket": self._row(existing),
                    }

            ticket_id = "TKT-" + uuid.uuid4().hex[:10].upper()
            history = [{
                "status": "SUBMITTED", "at": now, "actor": "guest",
                "note": "ticket_created",
            }]
            conn.execute("""INSERT INTO tickets (
                ticket_id, guest_id, booking_id, category, description, priority, status,
                assigned_to, idempotency_key, created_at, updated_at, history_json,
                metadata_json, operation_id, issue_type
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                ticket_id, str(guest_id), normalized_booking_id, category, description,
                priority, "SUBMITTED", None, key, now, now,
                json.dumps(history, ensure_ascii=False),
                json.dumps(metadata, ensure_ascii=False), operation_id, issue_type,
            ))
            row = conn.execute(
                "SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
            return {"ok": True, "created": True, "ticket": self._row(row)}

    def get_active_ticket(self, booking_id, issue_type, guest_id=None):
        """Return the active ticket for a booking/issue pair, optionally owner-scoped."""
        normalized_issue_type = normalize_issue_type(issue_type)
        with self._connection() as conn:
            if guest_id is None:
                row = conn.execute("""
                    SELECT * FROM tickets
                    WHERE booking_id=? AND issue_type=?
                      AND status IN ('SUBMITTED', 'ASSIGNED', 'PROCESSING',
                                     'PENDING_USER', 'ESCALATED')
                    ORDER BY created_at DESC LIMIT 1
                """, (str(booking_id), normalized_issue_type)).fetchone()
            else:
                row = conn.execute("""
                    SELECT * FROM tickets
                    WHERE booking_id=? AND issue_type=? AND guest_id=?
                      AND status IN ('SUBMITTED', 'ASSIGNED', 'PROCESSING',
                                     'PENDING_USER', 'ESCALATED')
                    ORDER BY created_at DESC LIMIT 1
                """, (str(booking_id), normalized_issue_type, str(guest_id))).fetchone()
        return self._row(row) if row else None

    def get_ticket(self, ticket_id, guest_id=None, staff=False):
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
        if row is None or (not staff and (not guest_id or row["guest_id"] != str(guest_id))):
            return {"ok": False, "error": "not_found"}
        return {"ok": True, "ticket": self._row(row)}

    def list_tickets(self, guest_id=None, staff=False, limit=100):
        with self._connection() as conn:
            if staff:
                rows = conn.execute(
                    "SELECT * FROM tickets ORDER BY created_at DESC LIMIT ?", (int(limit),)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tickets WHERE guest_id=? ORDER BY created_at DESC LIMIT ?",
                    (str(guest_id or ""), int(limit)),
                ).fetchall()
        return [self._row(row) for row in rows]

    def update_ticket(self, ticket_id, status, actor, note="", assigned_to=None):
        status = str(status or "").strip().upper()
        if status not in STATUSES:
            return {"ok": False, "error": "invalid_status"}
        with self._connection(write=True) as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "not_found"}
            current = row["status"]
            if status not in TRANSITIONS.get(current, set()):
                return {
                    "ok": False, "error": "invalid_transition",
                    "current_status": current,
                }
            history = json.loads(row["history_json"])
            history.append({
                "status": status, "at": self._now(), "actor": str(actor),
                "note": str(note or ""), "assigned_to": assigned_to,
            })
            conn.execute("""UPDATE tickets SET status=?, assigned_to=COALESCE(?, assigned_to),
                updated_at=?, history_json=? WHERE ticket_id=?""", (
                status, assigned_to, self._now(),
                json.dumps(history, ensure_ascii=False), ticket_id,
            ))
            updated = conn.execute(
                "SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)
            ).fetchone()
            return {"ok": True, "ticket": self._row(updated)}

    @staticmethod
    def _row(row):
        item = dict(row)
        item["history"] = json.loads(item.pop("history_json"))
        item["metadata"] = json.loads(item.pop("metadata_json", "{}") or "{}")
        item["metadata"]["issue_type"] = item.get("issue_type") or item["metadata"].get("issue_type")
        return item
