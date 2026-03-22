"""
Fan-out via list comprehension - homogeneous parallel dispatch.

Each topic is processed by the same actor in parallel. Results are
collected into p["results"] by the fan-in aggregator.
"""

from _asya_utils import actor, flow


@flow
def research_flow(p: dict) -> dict:
    p = preprocessor(p)
    p["results"] = [research_agent(t) for t in p["topics"]]
    p = post_processor(p)
    return p


@actor
def preprocessor(p: dict) -> dict:
    """Prepare topics for research."""
    return p


@actor
def research_agent(topic: dict) -> dict:
    """Research a single topic."""
    return topic


@actor
def post_processor(p: dict) -> dict:
    """Merge and summarize research results."""
    return p
