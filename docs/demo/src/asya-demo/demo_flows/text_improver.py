"""
Evaluator-Optimizer: generate text, score it, loop until good enough.

Demo flow for KubeCon + CloudNativeCon Europe 2026.
Compiles to distributed actor graph via `asya flow compile flow.py`.
"""

from demo_actors.generator import generator
from demo_actors.evaluator import evaluator
from demo_actors.polisher import polisher
from .asya_utils import flow

SCORE_THRESHOLD = 80
MAX_ITERATIONS = 3

@flow
async def text_improver(state: dict) -> dict:
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
