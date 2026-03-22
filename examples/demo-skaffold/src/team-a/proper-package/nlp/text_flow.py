"""Text analysis flow: analyze sentiment, then summarize.

Uses package actors from src/team-a/packages/nlp/.
Compiles to: start-text-flow -> analyze -> summarize -> x-sink
"""
from .analyzer import analyze
from .summarizer import summarize


def text_flow(payload: dict) -> dict:  # asya: flow
    payload = analyze(payload)    # asya: actor
    payload = summarize(payload)  # asya: actor
    return payload
