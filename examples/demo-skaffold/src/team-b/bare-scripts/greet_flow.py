"""Greeting flow: greet, run text analysis, then shout.

Uses bare-script actors (greeter.py, shouter.py) plus imports
text_flow as a plain Python function — the compiler inlines it,
expanding analyze + summarize into this flow's actor graph.

Compiles to: start-greet-flow -> greet -> analyze -> summarize -> shout -> x-sink
"""
from greeter import greet
from shouter import shout

def greet_flow(payload: dict) -> dict:  # asya: flow
    payload["greet"] = greet(payload)
    payload["shout"] = shout(payload)  # asya: actor
    return payload
