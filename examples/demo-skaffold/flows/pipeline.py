"""Demo flow: analyze -> summarize -> translate.

Cross-team flow: uses team-a actors (sentiment, summarizer)
and team-b actor (translator). Compiles to AsyncActor CRDs
via `asya compile team-a/flows/pipeline.py`.
"""
from sentiment_actors.handler import analyze
from summarizer.handler import summarize
from translator.handler import translate
from .asya_utils import flow, actor


@flow
def pipeline(payload: dict) -> dict:
    payload = analyze(payload)  # asya: actor
    payload = summarize(payload)  # asya: actor
    payload = translate(payload)  # asya: actor
    return payload
