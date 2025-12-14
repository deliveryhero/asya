def test_nested_flow(p: dict) -> dict:
    p = validate_input(p)

    if p["level1"] == "A":
        p["path"] = "A"
        if p["level2"] == "X":
            p["route"] = "A-X"
            p = route_a_x(p)
        else:
            p["route"] = "A-Y"
            p = route_a_y(p)
    else:
        p["path"] = "B"
        if p["level2"] == "X":
            p["route"] = "B-X"
            p = route_b_x(p)
        else:
            p["route"] = "B-Y"
            p = route_b_y(p)

    p = finalize_result(p)
    return p


def validate_input(p: dict) -> dict:
    """Validate input payload has required fields."""
    if "level1" not in p or "level2" not in p:
        raise ValueError("Missing required fields: level1, level2")
    p["validated"] = True
    return p


def route_a_x(p: dict) -> dict:
    """Process A-X route."""
    p["processed_by"] = "route_a_x"
    p["result"] = "A-X complete"
    return p


def route_a_y(p: dict) -> dict:
    """Process A-Y route."""
    p["processed_by"] = "route_a_y"
    p["result"] = "A-Y complete"
    return p


def route_b_x(p: dict) -> dict:
    """Process B-X route."""
    p["processed_by"] = "route_b_x"
    p["result"] = "B-X complete"
    return p


def route_b_y(p: dict) -> dict:
    """Process B-Y route."""
    p["processed_by"] = "route_b_y"
    p["result"] = "B-Y complete"
    return p


def finalize_result(p: dict) -> dict:
    """Finalize processing and mark as complete."""
    p["status"] = "completed"
    p["final"] = True
    return p
