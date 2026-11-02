"""Authorization-first, read-only booking query service for MVP 1.3."""
from datetime import datetime, timezone
from services.identity import principal_is_valid
from services.booking_repository import BookingRepository
from services.audit import build_audit_event

ALLOWED_FILTERS = {"check_in_from", "check_in_to", "room_type", "property_id", "booking_status"}
SUMMARY_FIELDS = ("booking_id", "property_id", "booking_status", "room_type", "check_in", "check_out")

class BookingService:
    def __init__(self, repository=None):
        self.repository = repository or BookingRepository()
        self.audit_events = []

    def _audit(self, principal, booking_id, action, status):
        event = build_audit_event(principal, booking_id, action, status)
        self.audit_events.append(event)
        return event["audit_id"]

    def _owned_bookings(self, principal):
        if not principal_is_valid(principal):
            return None
        return [b for b in self.repository.list_bookings() if b.get("customer_id") == principal.customer_id]

    def _summary(self, booking):
        return {k: booking.get(k) for k in SUMMARY_FIELDS}

    def search_my_bookings(self, principal, filters=None, limit=3):
        if not principal_is_valid(principal):
            self._audit(principal, None, "search_bookings", "unauthenticated")
            return {"status": "unauthenticated", "matched_bookings": [], "audit_id": self.audit_events[-1]["audit_id"]}
        filters = filters or {}
        if set(filters) - ALLOWED_FILTERS:
            self._audit(principal, None, "search_bookings", "invalid_filters")
            return {"status": "invalid_filters", "matched_bookings": [], "audit_id": self.audit_events[-1]["audit_id"]}
        try:
            rows = self._owned_bookings(principal)
        except Exception:
            audit_id = self._audit(principal, None, "search_bookings", "tool_error")
            return {"status": "tool_error", "matched_bookings": [], "audit_id": audit_id}
        if "check_in_from" in filters:
            rows = [b for b in rows if b.get("check_in","")[:10] >= str(filters["check_in_from"])]
        if "check_in_to" in filters:
            rows = [b for b in rows if b.get("check_in","")[:10] <= str(filters["check_in_to"])]
        if "room_type" in filters:
            rows = [b for b in rows if str(filters["room_type"]).lower() in b.get("room_type","").lower()]
        if "property_id" in filters:
            rows = [b for b in rows if b.get("property_id") == filters["property_id"]]
        if "booking_status" in filters:
            rows = [b for b in rows if b.get("booking_status") == filters["booking_status"]]
        rows.sort(key=lambda b: (b.get("check_in",""), b.get("created_at","")), reverse=True)
        try:
            limit = max(1, min(int(limit), 3))
        except (TypeError, ValueError):
            limit = 3
        status = "ok" if rows else "not_found"
        audit_id = self._audit(principal, None, "search_bookings", status)
        return {"status": status, "matched_bookings": [self._summary(b) for b in rows[:limit]], "audit_id": audit_id}

    def get_my_booking(self, principal, booking_id):
        if not principal_is_valid(principal):
            audit_id = self._audit(principal, booking_id, "get_booking", "unauthenticated")
            return {"status": "unauthenticated", "booking": None, "audit_id": audit_id}
        # Do not reveal whether an ID exists but belongs to another customer.
        try:
            booking = next((b for b in self.repository.list_bookings()
                            if b.get("booking_id") == booking_id and b.get("customer_id") == principal.customer_id), None)
        except Exception:
            audit_id = self._audit(principal, booking_id, "get_booking", "tool_error")
            return {"status": "tool_error", "booking": None, "audit_id": audit_id}
        if not booking:
            audit_id = self._audit(principal, booking_id, "get_booking", "not_found_or_forbidden")
            return {"status": "not_found", "booking": None, "audit_id": audit_id}
        try:
            prop = self.repository.get_property(booking.get("property_id"))
            policy = self.repository.get_policy(booking.get("cancellation_policy_id"))
        except Exception:
            audit_id = self._audit(principal, booking_id, "get_booking_detail", "tool_error")
            return {"status": "tool_error", "booking": None, "audit_id": audit_id}
        missing = []
        if not policy:
            missing.append("cancellation_policy")
        if not prop:
            missing.append("property")
        detail = {
            "booking": {k: booking.get(k) for k in (
                "booking_id","booking_status","room_type","check_in","check_out","guest_count",
                "breakfast_entitlement","parking_entitlement","source_channel"
            )},
            "property": ({k: prop.get(k) for k in ("property_id","property_name","property_type","location","facilities","check_in_instructions")} if prop else None),
            "cancellation_policy": ({k: policy.get(k) for k in ("policy_id","version","timezone","effective_from","effective_to","windows")} if policy else None),
            "missing_fields": missing,
        }
        status = "data_incomplete" if missing else "ok"
        audit_id = self._audit(principal, booking_id, "get_booking_detail", status)
        return {"status": status, **detail, "audit_id": audit_id}
