"""Polisher actor: final formatting pass on the approved draft."""

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .asya_utils import actor


@actor
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(litellm.exceptions.APIConnectionError),
)
async def polisher(payload: dict) -> dict:
    draft = payload.get("draft", "")
    task = payload.get("task", "")

    prompt = (
        f"Polish this text for publication. Fix grammar, improve flow, "
        f"keep the style. Do not add commentary, return only the polished text.\n\n"
        f"Task: {task}\n"
        f"Text:\n{draft}"
    )
    response = await litellm.acompletion(
        model="vertex_ai/gemini-2.0-flash",
        messages=[{"role": "user", "content": prompt}],
        timeout=600,
    )

    payload["final_output"] = response.choices[0].message.content
    print(f"[+] done\n\n{payload['final_output']}")
    return payload
