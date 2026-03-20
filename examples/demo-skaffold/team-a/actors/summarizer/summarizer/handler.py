"""Summarizer actor: returns a naive summary (first N words) of the input text."""
from .asya_utils import actor


@actor
def summarize(payload: dict) -> dict:
    text = payload.get("text", "")
    max_words = payload.get("max_words", 20)

    words = text.split()
    if len(words) > max_words:
        summary = " ".join(words[:max_words]) + "..."
    else:
        summary = text

    payload["summary"] = summary
    print(f"[+] summarized to {len(summary)} chars")
    return payload
