"""Research actor: gather context about a topic."""
import random
import time


async def research(topic: str) -> str:  # asya: actor
    time.sleep(random.random())
    context = (
        f"Key facts about '{topic}': "
        f"This is a well-studied subject with multiple perspectives. "
        f"Recent developments include new frameworks and methodologies. "
        f"Consider both technical and human aspects."
    )
    print(f"[+] researched context for '{topic}'")
    return context
