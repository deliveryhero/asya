"""Sentiment analysis actor: returns a sentiment score for the input text."""
from common.utils import word_count
from .asya_utils import actor


@actor
def analyze(payload: dict) -> dict:
    text = payload.get("text", "")
    positive_words = {"good", "great", "excellent", "happy", "wonderful", "love", "best"}
    negative_words = {"bad", "terrible", "awful", "sad", "worst", "hate", "poor"}

    tokens = text.lower().split()
    pos = sum(1 for t in tokens if t in positive_words)
    neg = sum(1 for t in tokens if t in negative_words)
    total = max(len(tokens), 1)

    score = (pos - neg) / total
    payload["sentiment_score"] = round(score, 3)
    payload["word_count"] = word_count(text)
    print(f"[+] sentiment score={payload['sentiment_score']}, words={payload['word_count']}")
    return payload
