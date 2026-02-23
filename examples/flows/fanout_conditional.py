"""
Fan-out inside conditional - choose strategy based on payload.

When parallel mode is enabled, process items via fan-out.
Otherwise, fall back to a sequential handler.
"""


def adaptive_flow(p: dict) -> dict:
    p = classifier(p)

    if p["parallel"]:
        p["results"] = [
            fast_analyzer(p["text"]),
            deep_analyzer(p["text"]),
        ]
    else:
        p = sequential_analyzer(p)

    p = formatter(p)
    return p


def classifier(p: dict) -> dict:
    """Decide whether to use parallel or sequential processing."""
    return p


def fast_analyzer(text: dict) -> dict:
    """Quick surface-level analysis."""
    return text


def deep_analyzer(text: dict) -> dict:
    """Thorough deep analysis."""
    return text


def sequential_analyzer(p: dict) -> dict:
    """Fallback sequential analysis."""
    return p


def formatter(p: dict) -> dict:
    """Format final results."""
    return p
