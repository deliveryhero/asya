"""
Try-except with fully-qualified exception types.

Demonstrates catching vendor-specific errors by FQN (e.g. openai.RateLimitError).
The sidecar matches FQN types exactly against the error's module.class path.
"""

from _asya_utils import flow


@flow
def llm_pipeline(p: dict) -> dict:
    p["model"] = "gpt-4"
    try:
        p = call_llm(p)
    except openai.RateLimitError:
        p["fallback"] = True
        p = call_fallback_llm(p)
    except openai.AuthenticationError:
        p["status"] = "auth_failed"
        p = notify_admin(p)
    return p
