"""
Loop processing flow example.

Demonstrates while loops with break and continue statements.
"""

from typing import Dict


def initialize(p: Dict) -> Dict:
    """Initialize processing state."""
    p["iteration"] = 0
    p["max_iterations"] = p.get("max_iterations", 5)
    return p


def process_item(p: Dict) -> Dict:
    """Process single iteration."""
    p["iteration"] += 1
    p["last_processed"] = p["iteration"]
    return p


def check_threshold(p: Dict) -> Dict:
    """Check if threshold is met."""
    p["threshold_met"] = p["iteration"] >= p.get("threshold", 3)
    return p


def finalize_loop(p: Dict) -> Dict:
    """Finalize after loop completion."""
    p["completed"] = True
    return p


def flow_loop_processing(p: Dict) -> Dict:
    p = initialize(p)

    while p["iteration"] < p["max_iterations"]:
        p = process_item(p)

        if p.get("skip_threshold_check"):
            continue

        p = check_threshold(p)

        if p["threshold_met"]:
            break

    p = finalize_loop(p)
    return p
