"""Evaluator actor: score the draft and provide feedback for improvement."""

import json

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .asya_utils import actor


@actor
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(litellm.exceptions.APIConnectionError),
)
async def evaluator(payload: dict) -> dict:
    task = payload.get("task", "")
    draft = payload.get("draft", "")

    prompt = (
        f"You are a writing critic. Score this text 0-100 and give feedback.\n\n"
        f"Task: {task}\n"
        f"Text:\n{draft}\n\n"
        f'Respond in JSON: {{"score": <int>, "feedback": "<specific improvements>"}}'
    )
    response = await litellm.acompletion(
        model="vertex_ai/gemini-2.0-flash",
        messages=[{"role": "user", "content": prompt}],
        timeout=600,
    )

    raw = response.choices[0].message.content
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(cleaned)
        payload["score"] = int(result.get("score", 0))
        payload["feedback"] = result.get("feedback", "")
    except (json.JSONDecodeError, ValueError):
        payload["score"] = 50
        payload["feedback"] = raw

    print(f"[+] score: {payload['score']}/100")
    return payload
