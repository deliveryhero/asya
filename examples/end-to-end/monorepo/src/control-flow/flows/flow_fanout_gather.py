"""
Fan-out via asyncio.gather - async parallel dispatch.

Demonstrates both gather patterns: generator expression for
homogeneous fan-out and explicit args for heterogeneous fan-out.
"""

import asyncio

from _asya_utils import flow


@flow
async def async_research_flow(p: dict) -> dict:
    p = await preprocessor(p)
    p["results"] = await asyncio.gather(*(research_agent(t) for t in p["topics"]))
    p = await postprocessor(p)
    return p


async def preprocessor(p: dict) -> dict:
    """Prepare topics for research."""
    return p


async def research_agent(topic: dict) -> dict:
    """Research a single topic."""
    return topic


async def postprocessor(p: dict) -> dict:
    """Merge and summarize research results."""
    return p
