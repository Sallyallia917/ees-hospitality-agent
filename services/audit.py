"""Minimal in-memory audit event builder; demo only, no production observability claim."""
from datetime import datetime, timezone
from uuid import uuid4

def build_audit_event(principal, booking_id, action, result_status):
    return {
        "audit_id": str(uuid4()),
        "principal_id": getattr(principal, "principal_id", None),
        "booking_id": booking_id,
        "action": action,
        "result_status": result_status,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
