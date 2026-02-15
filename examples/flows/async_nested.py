"""
Nested async conditionals - sequential awaits in branches.

A review pipeline that performs an initial review, then routes
to either a detailed + human review path or an auto-approve path
based on the review score. Demonstrates nested await chains
inside conditional branches.
"""


async def review_pipeline_flow(state: dict) -> dict:
    state = await initial_review(state)
    if state["score"] < 0.5:
        state = await detailed_review(state)
        state = await human_review(state)
    else:
        state = await auto_approve(state)
    return state


async def initial_review(state: dict) -> dict:
    """Run initial automated review and produce a score."""
    return state


async def detailed_review(state: dict) -> dict:
    """Deep analysis for low-scoring submissions."""
    return state


async def human_review(state: dict) -> dict:
    """Route to human reviewer for final decision."""
    return state


async def auto_approve(state: dict) -> dict:
    """Auto-approve high-scoring submissions."""
    return state
