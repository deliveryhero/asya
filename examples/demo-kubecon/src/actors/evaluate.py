"""Evaluator actor: score the draft and provide feedback."""
import random
import time


async def evaluate(payload: dict) -> dict:  # asya: actor
    time.sleep(random.random())
    iteration = payload.get("iteration", 1)
    base_score = 50 + iteration * 18
    payload["score"] = min(base_score + random.randint(-5, 5), 100)
    if payload["score"] < payload.get("threshold", 85):
        payload["feedback"] = (
            f"Score {payload['score']}/100. "
            f"Needs stronger transitions, more concrete examples, "
            f"and better conclusion. Iteration {iteration}."
        )
    else:
        payload["feedback"] = ""
    print(f"[+] evaluated: score={payload['score']}/100 (iteration {iteration})")
    return payload
