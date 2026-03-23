# fmt: off
# ruff: noqa
"""Auto-generated adapter for format_greeting"""

def adapter_format_greeting(payload: dict):
    """Adapter: wraps format_greeting() for dict-in/dict-out protocol"""
    _result = format_greeting(payload['user_name'])
    payload['greeting'] = _result
    yield payload
