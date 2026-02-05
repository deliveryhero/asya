"""
Loop processing flow example.

Demonstrates while loops with break and continue statements.
"""


def loop_flow(p: dict) -> dict:
    p = initialize(p)

    p["iteration"] = 0
    while p["iteration"] < p["max_iterations"]:
        p["iteration"] += 1
        p = process_item(p)

        if p.get("skip_threshold_check"):
            p['abort'] = 1
            p = process_abort(p)
            p['abort'] = 2
            continue
        p = check_threshold(p)

        if p["threshold_met"]:
            break

    p = finalize_loop(p)
    return p


def process_abort(p: dict) -> dict:
    return None

def initialize(p: dict) -> dict:
    """Initialize processing state."""
    p["iteration"] = 0
    p["max_iterations"] = p.get("max_iterations", 5)
    return p


def process_item(p: dict) -> dict:
    """Process single iteration."""
    p["iteration"] += 1
    p["last_processed"] = p["iteration"]
    return p


def check_threshold(p: dict) -> dict:
    """Check if threshold is met."""
    p["threshold_met"] = p["iteration"] >= p.get("threshold", 3)
    return p


def finalize_loop(p: dict) -> dict:
    """Finalize after loop completion."""
    p["completed"] = True
    return p
