"""Generator actor: produce or revise a draft based on the task and feedback."""

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from .asya_utils import actor


@actor
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(litellm.exceptions.APIConnectionError),
)
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

    response = await litellm.acompletion(
        model="vertex_ai/gemini-2.0-flash",
        messages=[{"role": "user", "content": prompt}],
    )
    payload["draft"] = response.choices[0].message.content
    return payload
