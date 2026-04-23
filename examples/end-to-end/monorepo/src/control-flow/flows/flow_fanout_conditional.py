"""
Fan-out inside conditional - choose strategy based on payload.

When parallel mode is enabled, process items via fan-out.
Otherwise, fall back to a sequential handler.
"""

from _asya_utils import actor, flow


@flow
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


@actor
def classifier(p: dict) -> dict:
    """Decide whether to use parallel or sequential processing."""
    return p


@actor
def fast_analyzer(text: dict) -> dict:
    """Quick surface-level analysis."""
    return text


@actor
def deep_analyzer(text: dict) -> dict:
    """Thorough deep analysis."""
    return text


@actor
def sequential_analyzer(p: dict) -> dict:
    """Fallback sequential analysis."""
    return p


@actor
def formatter(p: dict) -> dict:
    """Format final results."""
    return p
