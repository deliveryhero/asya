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
    print(f"[.] task: {state.get('task', '?')}")
    state["iteration"] = 0

    while True:
        state["iteration"] += 1
        print(f"\n--- iteration {state['iteration']} ---")

        print("[.] generator ...")
        state = await generator(state)
        preview = state.get("draft", "")[:100].replace("\n", " ")
        print(f"[+] draft: {preview}...")

        print("[.] evaluator ...")
        state = await evaluator(state)
        print(f"[+] score: {state.get('score', '?')}/100")

        if state.get("score", 0) >= SCORE_THRESHOLD:
            print(f"[+] passed threshold ({SCORE_THRESHOLD})")
            break

        print(f"[-] below threshold ({SCORE_THRESHOLD}), feedback: {state.get('feedback', '')[:100]}")
        if state["iteration"] >= MAX_ITERATIONS:
            print(f"[!] max iterations reached ({MAX_ITERATIONS})")
            break

    print("\n[.] polisher ...")
    state = await polisher(state)
    print(f"[+] done\n")
    return state
