"""
Evaluator-Optimizer: generate text, score it, loop until good enough.

Demo flow for KubeCon + CloudNativeCon Europe 2026.
Compiles to distributed actor graph via `asya flow compile flow.py`.
"""

from demo_actors.generator import generator
from demo_actors.evaluator import evaluator
from demo_actors.polisher import polisher

SCORE_THRESHOLD = 90
MAX_ITERATIONS = 3


async def agentic_flow(state: dict) -> dict:  # asya: flow
    state["iteration"] = 0

    while True:
        state["iteration"] += 1

        state = await generator(state)
        state = await evaluator(state)

        if state.get("score", 0) >= SCORE_THRESHOLD:
            break

        if state["iteration"] >= MAX_ITERATIONS:
            break

    state = await polisher(state)
    return state
