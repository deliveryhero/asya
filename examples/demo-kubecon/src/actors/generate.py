"""Generator actor: write or revise a draft using Gemini."""
import litellm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(litellm.exceptions.APIConnectionError),
)
async def generate(topic: str, context: str) -> str:  # asya: actor
    prompt = (
        f"Write a short, creative text (3-5 paragraphs) about: {topic}\n\n"
        f"Use this context:\n{context}\n\n"
        f"Be engaging and informative."
    )
    response = await litellm.acompletion(
        model="vertex_ai/gemini-2.0-flash",
        messages=[{"role": "user", "content": prompt}],
    )
    draft = response.choices[0].message.content
    print(f"[+] generated draft ({len(draft)} chars)")
    return draft
