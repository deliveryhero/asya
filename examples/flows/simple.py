"""
Simple linear flow example.

Demonstrates basic sequential handler execution without control flow.
"""


def simple_flow(p: dict) -> dict:
    p = handler_preprocess(p)
    p = handler_analyze(p)
    p["key"] += 1
    if p["key"] == 1:
        p = handler_analyze(p)
    p = handler_format_output(p)
    return p


def handler_preprocess(p: dict) -> dict:
    """Mock preprocessor handler."""
    ...
    p["preprocessed"] = True
    return p


def handler_analyze(p: dict) -> dict:
    """Mock analyzer handler."""
    ...
    p["analyzed"] = True
    return p


def handler_format_output(p: dict) -> dict:
    """Mock formatter handler."""
    ...
    p["formatted"] = True
    return p
