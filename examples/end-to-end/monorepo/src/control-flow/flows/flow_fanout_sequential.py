"""
Sequential fan-out - two fan-out stages in the same flow.

First stage researches topics in parallel. Second stage reviews
each research result in parallel. Each fan-out/fan-in completes
before the next one starts.
"""

from _asya_utils import actor, flow


@flow
def multi_stage_flow(p: dict) -> dict:
    p["research"] = [research_agent(t) for t in p["topics"]]
    p["reviews"] = [review_agent(r) for r in p["research"]]
    p = summarizer(p)
    return p


@actor
def research_agent(topic: dict) -> dict:
    """Research a single topic."""
    return topic


@actor
def review_agent(result: dict) -> dict:
    """Review a single research result."""
    return result


@actor
def summarizer(p: dict) -> dict:
    """Summarize all reviewed research."""
    return p
