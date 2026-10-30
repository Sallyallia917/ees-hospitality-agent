VALID_ORDER_STATUSES = {"UNKNOWN", "UNVERIFIED", "VERIFIED"}

def default_context():
    return {"order_status": "UNKNOWN", "booking_id": None, "user_id": None}

def update_order_status(context, status):
    if status not in VALID_ORDER_STATUSES:
        raise ValueError("Unsupported order status")
    updated = dict(context or default_context())
    updated["order_status"] = status
    return updated
