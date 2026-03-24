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


async def generate(topic: str, context: str) -> str:  # asya: actor
    t = random.random()
    print(f"[.] Sleeping random {t:.3} sec")
    time.sleep(t)

    if random.random() < FAIL_RATE:
        raise RuntimeError("[!] transient generation failure")

    if not context:
        draft = f"[{topic}] {FIRST_DRAFT}"
    else:
        draft = f"[{topic}] {REVISION} (Addressed: {context[:60]})"
    print(f"[+] generated draft ({len(draft)} chars)")
    return draft
