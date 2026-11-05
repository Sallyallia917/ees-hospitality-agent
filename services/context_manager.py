"""Explicit dialogue state for authenticated booking conversations."""
VALID_ORDER_STATUSES = {"UNKNOWN", "UNVERIFIED", "VERIFIED"}

def default_context():
    return {
        "order_status": "UNKNOWN", "booking_id": None, "user_id": None,
        "active_booking_id": None, "candidate_booking_ids": [],
        "candidate_booking_summaries": [], "last_intent": None,
        "last_sub_intent": None, "pending_action": None, "dialogue_stage": "idle",
        "pending_transaction_type": None, "pending_issue_text": None,
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

def clear_dialogue_state(context):
    state = context if isinstance(context, dict) else default_context()
    state.update(default_context())
    return state
