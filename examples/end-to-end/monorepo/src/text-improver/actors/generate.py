"""Generator actor: write a draft using Gemini."""

import litellm
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(litellm.exceptions.APIConnectionError),
)
async def generate(query: str, context: str) -> str:  # asya: actor
    response = await litellm.acompletion(
        model="vertex_ai/gemini-2.0-flash",
        messages=[{"role": "user", "content": f"Write 2 paragraphs about: {query}\nContext: {context}"}],
        max_tokens=300,
    )
    draft = response.choices[0].message.content
    print(f"[+] generated draft ({len(draft)} chars)")
    return draft
