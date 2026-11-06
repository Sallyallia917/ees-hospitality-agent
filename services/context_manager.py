"""Explicit dialogue and operation state for authenticated booking conversations."""
import uuid
VALID_ORDER_STATUSES = {"UNKNOWN", "UNVERIFIED", "VERIFIED"}

def default_context():
    return {
        "order_status": "UNKNOWN", "booking_id": None, "user_id": None,
        "active_booking_id": None, "candidate_booking_ids": [],
        "candidate_booking_summaries": [], "last_intent": None,
        "last_sub_intent": None, "pending_action": None, "dialogue_stage": "idle",
        "pending_transaction_type": None, "pending_issue_text": None,
        "current_operation": None, "booking_operations": [], "operation_sequence": 0,
    }

def update_order_status(context, status):
    if status not in VALID_ORDER_STATUSES:
        raise ValueError("Unsupported order status")
    updated = dict(context or default_context())
    updated["order_status"] = status
    return updated

def remember_intent(context, intent, sub_intent=None):
    state = context if isinstance(context, dict) else default_context()
    state["last_intent"], state["last_sub_intent"] = intent, sub_intent
    return state

def remember_candidates(context, bookings, pending_action="select_booking"):
    state = context if isinstance(context, dict) else default_context()
    rows = bookings or []
    state["candidate_booking_ids"] = [b.get("booking_id") for b in rows if b.get("booking_id")]
    state["candidate_booking_summaries"] = [
        {k: b.get(k) for k in ("booking_id", "room_type", "property_name", "property_id", "check_in", "check_out", "booking_status")}
        for b in rows if b.get("booking_id")
    ]
    state["pending_action"] = pending_action if state["candidate_booking_ids"] else None
    state["dialogue_stage"] = "awaiting_booking_selection" if state["candidate_booking_ids"] else "idle"
    return state

def remember_active_booking(context, booking_id):
    state = context if isinstance(context, dict) else default_context()
    state["active_booking_id"] = state["booking_id"] = booking_id
    state["candidate_booking_ids"] = []
    state["candidate_booking_summaries"] = []
    state["pending_action"] = None
    state["dialogue_stage"] = "booking_selected"
    return state

def begin_operation(context, booking_id, operation_type):
    state = context if isinstance(context, dict) else default_context()
    state["operation_sequence"] = int(state.get("operation_sequence") or 0) + 1
    operation = {
        "operation_id": "OP-" + uuid.uuid4().hex[:12].upper(),
        "booking_id": booking_id,
        "operation_type": operation_type,
        "stage": "awaiting_confirmation" if operation_type == "cancel_or_refund" else "awaiting_issue_details",
        "user_confirmed": False,
        "status": "in_progress",
        "ticket_id": None,
    }
    state["current_operation"] = operation
    state["active_booking_id"] = state["booking_id"] = booking_id
    state["pending_action"] = "confirm_transaction" if operation_type == "cancel_or_refund" else "describe_booking_issue"
    state["pending_transaction_type"] = operation_type
    state["dialogue_stage"] = operation["stage"]
    return operation

def complete_operation(context, status, **extra):
    state = context if isinstance(context, dict) else default_context()
    operation = state.get("current_operation")
    if not isinstance(operation, dict):
        return None
    operation = dict(operation)
    operation["status"] = status
    operation.update(extra)
    if status in ("handed_off", "cancelled_by_user"):
        operation["stage"] = status
    state.setdefault("booking_operations", []).append(operation)
    state["current_operation"] = None
    state["active_booking_id"] = state["booking_id"] = None
    state["pending_action"] = None
    state["pending_transaction_type"] = None
    state["pending_issue_text"] = None
    state["dialogue_stage"] = "idle"
    return operation

def clear_dialogue_state(context):
    state = context if isinstance(context, dict) else default_context()
    state.update(default_context())
    return state
