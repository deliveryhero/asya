"""
Complex combined flow.

Tests combination of all patterns: if/elif/else + while + break/continue.
"""


def complex_combined_flow(p: dict) -> dict:
    p = handler_init(p)

    if not p["valid"]:
        p = handler_error(p)
        return p

    if p["needs_loop"]:
        p["i"] = 0
        while p["i"] < p["max_iterations"]:
            p["i"] += 1

            if p["skip_even"] and p["i"] % 2 == 0:
                continue

            p = handler_process(p)

            if p["stop_early"]:
                break
    else:
        if p["type"] == "A":
            p = handler_type_a(p)
        elif p["type"] == "B":
            p = handler_type_b(p)
        else:
            p = handler_default(p)

    p = handler_finalize(p)
    return p


def handler_init(p: dict) -> dict:
    """Initialize handler."""
    return p


def handler_error(p: dict) -> dict:
    """Error handler."""
    return p


def handler_process(p: dict) -> dict:
    """Process handler."""
    return p


def handler_type_a(p: dict) -> dict:
    """Type A handler."""
    return p


def handler_type_b(p: dict) -> dict:
    """Type B handler."""
    return p


def handler_default(p: dict) -> dict:
    """Default handler."""
    return p


def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
