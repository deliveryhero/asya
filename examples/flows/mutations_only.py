"""
Mutations without handlers.

Tests flow with only payload mutations, no handler calls.
"""


def mutations_only_flow(p: dict) -> dict:
    # so technically, it's not a flow but an actor!
    p["step"] = 1
    p["x"] = 10
    p["y"] = 20
    p["x"] += p["y"]
    return p
