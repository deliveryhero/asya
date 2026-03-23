# fmt: off
# ruff: noqa
"""Auto-generated adapter for calculate"""

def adapter_calculate(payload: dict):
    """Adapter: wraps calculate() for dict-in/dict-out protocol"""
    _result = calculate(payload['tool_args']['expression'])
    payload['tool_result'] = _result
    yield payload
