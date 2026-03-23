# fmt: off
# ruff: noqa
"""Auto-generated adapter for greet"""
from greeter import greet

def adapter_greet(payload: dict):
    """Adapter: wraps greet() for dict-in/dict-out protocol"""
    _result = greet(payload)
    payload['greeting'] = _result
    yield payload
