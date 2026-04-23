"""Evaluator actor: score the draft using Gemini."""

import json

import litellm
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(litellm.exceptions.APIConnectionError),
)
async def evaluate(payload: dict) -> dict:  # asya: actor
    draft = payload.get("draft", payload.get("result", ""))

    response = await litellm.acompletion(
        model="vertex_ai/gemini-2.0-flash",
        messages=[
            {
                "role": "user",
                "content": f'Score 0-100 and give feedback. Respond JSON only: {{"score":<int>,"feedback":"<text>"}}\n\nText:\n{draft[:500]}',
            }
        ],
        max_tokens=100,
    )
    raw = response.choices[0].message.content
    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(cleaned)
        payload["score"] = int(result.get("score", 0))
        payload["feedback"] = result.get("feedback", "")
    except (json.JSONDecodeError, ValueError):
        payload["score"] = 50
        payload["feedback"] = raw

    print(f"[+] evaluated: score={payload['score']}/100")
    return payload
