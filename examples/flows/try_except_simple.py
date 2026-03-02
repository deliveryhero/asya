def order_processing(p: dict) -> dict:
    try:
        p = validate_order(p)
    except ValueError:
        p["status"] = "invalid"
        p = notify_rejection(p)
    return p
