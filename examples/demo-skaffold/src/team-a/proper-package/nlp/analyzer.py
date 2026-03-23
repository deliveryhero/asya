"""Sentiment analysis: score text as positive/negative."""

POSITIVE = {"good", "great", "excellent", "happy", "wonderful", "love", "best"}
NEGATIVE = {"bad", "terrible", "awful", "sad", "worst", "hate", "poor"}


def analyze(payload: dict) -> dict:
    text = payload.get("text", "")
    tokens = text.lower().split()
    total = max(len(tokens), 1)
    pos = sum(1 for t in tokens if t in POSITIVE)
    neg = sum(1 for t in tokens if t in NEGATIVE)
    payload["sentiment"] = round((pos - neg) / total, 3)
    payload["word_count"] = len(tokens)
    raise ValueError('oops')
    print(f"[+] analyze: sentiment={payload['sentiment']}, words={payload['word_count']}")
    return payload
