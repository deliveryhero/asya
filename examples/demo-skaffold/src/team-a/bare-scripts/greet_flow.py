"""Greeting flow: greet, run text analysis, then shout.

Uses bare-script actors (greeter.py, shouter.py) plus imports
text_flow as a plain Python function — the compiler inlines it,
expanding analyze + summarize into this flow's actor graph.

Compiles to: start-greet-flow -> greet -> analyze -> summarize -> shout -> x-sink
"""
from greeter import greet
from shouter import shout
from nlp.summarizer import summarize
from nlp.text_flow import text_flow


def greet_flow(payload: dict) -> dict:  # asya: flow
    payload = greet(payload)      # asya: actor (bare script)
    payload = text_flow(payload)  # inlined: analyze -> summarize
    payload = shout(payload)      # asya: actor (bare script)
    payload["summary_of_summary"] = summarize(payload["summary"])
    return payload
