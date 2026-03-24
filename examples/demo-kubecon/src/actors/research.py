"""Research actor: gather context about a topic."""
import time
import random

async def research(topic: str) -> str:  # asya: actor
    t = random.random()
    print(f"[.] Sleeping random {t:.3} sec")
    time.sleep(t)
    context = (
        f"Key facts about '{topic}': "
        f"This is a well-studied subject with multiple perspectives. "
        f"Recent developments include new frameworks and methodologies. "
        f"Consider both technical and human aspects."
    )
    print(f"[+] researched context for '{topic}'")
    return context
