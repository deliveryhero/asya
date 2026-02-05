"""
Nested if statements.

Tests nested conditionals for complex decision trees.
"""


def nested_if_flow(p: dict) -> dict:
    p = handler_validate(p)
    if p["level1"] == "A":
        p["l1"] = "A"
        if p["level2"] == "X":
            p["l2"] = "X"
            p = handler_a_x(p)
        else:
            p["l2"] = "Y"
            p = handler_a_y(p)
    else:
        p["l1"] = "B"
        if p["level2"] == "X":
            p["l2"] = "X"
            p = handler_b_x(p)
        else:
            p["l2"] = "Y"
            p = handler_b_y(p)
    p = handler_finalize(p)
    return p


def handler_validate(p: dict) -> dict:
    """Validation handler."""
    return p


def handler_a_x(p: dict) -> dict:
    """A-X handler."""
    return p


def handler_a_y(p: dict) -> dict:
    """A-Y handler."""
    return p


def handler_b_x(p: dict) -> dict:
    """B-X handler."""
    return p


def handler_b_y(p: dict) -> dict:
    """B-Y handler."""
    return p


def handler_finalize(p: dict) -> dict:
    """Finalize handler."""
    return p
