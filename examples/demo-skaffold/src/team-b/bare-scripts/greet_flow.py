"""Greeting flow: greet then shout.

Uses bare-script actors (greeter.py, shouter.py).
Compiles to: start-greet-flow -> greet -> shout -> x-sink
"""
from greeter import greet
from shouter import shout


def greet_flow(payload: dict) -> dict:  # asya: flow
    payload = greet(payload)   # asya: actor
    payload = shout(payload)   # asya: actor
    return payload
