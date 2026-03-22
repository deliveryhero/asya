"""Sentiment analysis: score text as positive/negative."""

POSITIVE = {"good", "great", "excellent", "happy", "wonderful", "love", "best"}
NEGATIVE = {"bad", "terrible", "awful", "sad", "worst", "hate", "poor"}


def analyze(payload: dict) -> dict:  # asya: actor
    text = payload.get("text", "")
    tokens = text.lower().split()
    total = max(len(tokens), 1)
    pos = sum(1 for t in tokens if t in POSITIVE)
    neg = sum(1 for t in tokens if t in NEGATIVE)
    payload["sentiment"] = round((pos - neg) / total, 3)
    payload["word_count"] = len(tokens)
    print(f"[+] analyze: sentiment={payload['sentiment']}, words={payload['word_count']}")
    return payload
