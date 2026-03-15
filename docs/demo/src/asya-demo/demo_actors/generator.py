"""Generator actor: produce or revise a draft based on the task and feedback."""

from litellm import completion
from .asya_utils import actor

@actor
async def generator(payload: dict) -> dict:
    task = payload.get("task", "Write something interesting")
    iteration = payload.get("iteration", 1)
    feedback = payload.get("feedback", "")

    if iteration == 1:
        prompt = f"Write a short, creative text about: {task}"
    else:
        draft = payload.get("draft", "")
        prompt = (
            f"Revise this text based on the feedback.\n\n"
            f"Original task: {task}\n"
            f"Current draft:\n{draft}\n\n"
            f"Feedback:\n{feedback}\n\n"
            f"Write an improved version."
        )

    response = completion(
        model="vertex_ai/gemini-2.5-flash",
        messages=[{"role": "user", "content": prompt}],
    )
    payload["draft"] = response.choices[0].message.content
    return payload
