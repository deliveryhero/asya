"""Polisher actor: final formatting pass using Gemini."""

import litellm
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(litellm.exceptions.APIConnectionError),
)
async def polish(draft: str) -> str:  # asya: actor
    response = await litellm.acompletion(
        model="vertex_ai/gemini-2.0-flash",
        messages=[
            {
                "role": "user",
                "content": (
                    f"Polish this text for publication. Fix grammar, improve flow, "
                    f"keep the style. Return only the polished text.\n\n{draft}"
                ),
            }
        ],
    )
    polished = response.choices[0].message.content
    print(f"[+] polished ({len(polished)} chars)")
    return polished
