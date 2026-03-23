"""Naive summarizer: truncate to first N words."""


def summarize(payload: dict) -> dict:
    text = payload.get("text", "")
    limit = payload.get("summary_words", 10)
    words = text.split()
    payload["summary"] = " ".join(words[:limit]) + ("..." if len(words) > limit else "")
    print(f"[+] summarize: {len(payload['summary'])} chars")
    return payload
