"""Generator actor: write or revise a draft."""
import os
import random
import time

FAIL_RATE = float(os.environ.get("FAIL_RATE", "0"))

FIRST_DRAFT = (
    "Initial exploration of the topic. Covers basic concepts but lacks depth "
    "and structure. Needs more supporting evidence and clearer argumentation."
)

REVISION = (
    "Revised draft with improved structure and supporting evidence. "
    "Arguments are well-developed with concrete examples. "
    "Transitions between sections are smoother."
)


async def generate(topic: str, context: str, feedback: str) -> str:  # asya: actor
    if random.random() < FAIL_RATE:
        raise RuntimeError("[!] transient generation failure")

    time.sleep(random.random())
    if not feedback:
        draft = f"[{topic}] {FIRST_DRAFT}"
    else:
        draft = f"[{topic}] {REVISION} (Addressed: {feedback[:60]})"
    print(f"[+] generated draft ({len(draft)} chars)")
    return draft
