"""Research actor: gather context about a topic using Gemini."""
import litellm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(litellm.exceptions.APIConnectionError),
)
async def research(topic: str) -> str:  # asya: actor
    response = await litellm.acompletion(
        model="vertex_ai/gemini-2.0-flash",
        messages=[{"role": "user", "content": f"3 key facts about: {topic}. Max 2 sentences."}],
        max_tokens=150,
    )
    context = response.choices[0].message.content
    print(f"[+] researched '{topic}' ({len(context)} chars)")
    return context
