"""Polisher actor: final formatting pass on the approved draft."""

from litellm import completion

from .asya_utils import actor

@actor
async def polisher(payload: dict) -> dict:
    draft = payload.get("draft", "")
    task = payload.get("task", "")

    response = completion(
        model="vertex_ai/gemini-2.5-flash",
        messages=[
            {
                "role": "user",
                "content": (
                    f"Polish this text for publication. Fix grammar, improve flow, "
                    f"keep the style. Do not add commentary, return only the polished text.\n\n"
                    f"Task: {task}\n"
                    f"Text:\n{draft}"
                ),
            }
        ],
    )
    payload["final_output"] = response.choices[0].message.content
    return payload
