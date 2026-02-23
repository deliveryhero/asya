"""
Fan-out via list literal - heterogeneous parallel dispatch.

Different actors process the same input in parallel. Results are
collected into p["analysis"] by the fan-in aggregator.
"""


def analysis_flow(p: dict) -> dict:
    p["analysis"] = [
        sentiment_analyzer(p["text"]),
        topic_extractor(p["text"]),
        entity_recognizer(p["text"]),
    ]
    p = merge_analysis(p)
    return p


def sentiment_analyzer(text: dict) -> dict:
    """Analyze sentiment of the text."""
    return text


def topic_extractor(text: dict) -> dict:
    """Extract topics from the text."""
    return text


def entity_recognizer(text: dict) -> dict:
    """Recognize named entities in the text."""
    return text


def merge_analysis(p: dict) -> dict:
    """Combine all analysis results."""
    return p
