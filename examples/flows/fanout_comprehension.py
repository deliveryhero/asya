"""
Fan-out via list comprehension - homogeneous parallel dispatch.

Each topic is processed by the same actor in parallel. Results are
collected into p["results"] by the fan-in aggregator.
"""


def research_flow(state: dict) -> dict:
    state = preprocessor(state)
    state["results"] = [research_agent(t) for t in state["topics"]]
    state = post_processor(state)
    return state


def preprocessor(state: dict) -> dict:
    """Prepare topics for research."""
    return state


def research_agent(state: dict) -> dict:
    """Research a single topic."""
    return state


def post_processor(state: dict) -> dict:
    """Merge and summarize research results."""
    return state
