"""Evaluator actor: score the draft and provide feedback for improvement."""

import json

from litellm import completion
from .asya_utils import actor


@actor
async def evaluator(payload: dict) -> dict:
    task = payload.get("task", "")
    draft = payload.get("draft", "")

    response = completion(
        model="vertex_ai/gemini-2.5-flash",
        messages=[
            {
                "role": "user",
                "content": (
                    f"You are a writing critic. Score this text 0-100 and give feedback.\n\n"
                    f"Task: {task}\n"
                    f"Text:\n{draft}\n\n"
                    f'Respond in JSON: {{"score": <int>, "feedback": "<specific improvements>"}}'
                ),
            }
        ],
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

    return payload
