"""Research actor: gather context about a topic."""


async def research(topic: str) -> str:  # asya: actor
    context = (
        f"Key facts about '{topic}': "
        f"This is a well-studied subject with multiple perspectives. "
        f"Recent developments include new frameworks and methodologies. "
        f"Consider both technical and human aspects."
    )
    print(f"[+] researched context for '{topic}'")
    return context
