"""Greeting flow: greet then shout.

Uses bare-script actors (greeter.py, shouter.py).
Demonstrates both standard and adapter call patterns:
  - p = fn(p)            standard actor call
  - p["key"] = fn(p)     adapter call (compiler generates wrapper)

Compiles to: start-greet-flow -> greet -> shout -> x-sink
"""
from greeter import greet
from shouter import shout


def greet_flow(payload: dict) -> dict:  # asya: flow
    payload["greeting"] = greet(payload)
    payload = shout(payload)
    return payload
