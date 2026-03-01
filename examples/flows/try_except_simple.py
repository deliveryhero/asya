def order_processing(state: dict) -> dict:
    assert state.get("order_id"), "order_id is required"

    try:
        state = validate_order(state)
    except ValueError:
        state["status"] = "invalid"
        state = notify_rejection(state)
    return state
