"""Small, explicit dialogue state for the Streamlit conversation."""
VALID_ORDER_STATUSES = {"UNKNOWN", "UNVERIFIED", "VERIFIED"}

def default_context():
    return {
        "order_status": "UNKNOWN",
        "booking_id": None,
        "user_id": None,
        "active_booking_id": None,
        "candidate_booking_ids": [],
        "last_intent": None,
        "last_sub_intent": None,
        "pending_action": None,
        "dialogue_stage": "idle",
    }

def update_order_status(context, status):
    if status not in VALID_ORDER_STATUSES:
        raise ValueError("Unsupported order status")
    updated = dict(context or default_context())
    updated["order_status"] = status
    return updated

def remember_intent(context, intent, sub_intent=None):
    state = context if isinstance(context, dict) else default_context()
    state["last_intent"] = intent
    state["last_sub_intent"] = sub_intent
    return state

def remember_candidates(context, bookings):
    state = context if isinstance(context, dict) else default_context()
    state["candidate_booking_ids"] = [b.get("booking_id") for b in (bookings or []) if b.get("booking_id")]
    state["pending_action"] = "select_booking" if state["candidate_booking_ids"] else None
    state["dialogue_stage"] = "awaiting_booking_selection" if state["candidate_booking_ids"] else "idle"
    return state

def remember_active_booking(context, booking_id):
    state = context if isinstance(context, dict) else default_context()
    state["active_booking_id"] = booking_id
    state["booking_id"] = booking_id
    state["candidate_booking_ids"] = []
    state["pending_action"] = None
    state["dialogue_stage"] = "booking_selected"
    return state

def clear_dialogue_state(context):
    state = context if isinstance(context, dict) else default_context()
    for key in ("active_booking_id", "booking_id", "candidate_booking_ids", "pending_action"):
        state[key] = None if key != "candidate_booking_ids" else []
    state["dialogue_stage"] = "idle"
    state["last_intent"] = None
    state["last_sub_intent"] = None
    return state
