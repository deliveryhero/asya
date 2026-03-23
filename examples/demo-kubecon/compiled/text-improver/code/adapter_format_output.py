# fmt: off
# ruff: noqa
"""Auto-generated adapter for format_output"""
from actors import format_output

async def adapter_format_output(payload: dict):
    """Adapter: wraps format_output() for dict-in/dict-out protocol"""
    _result = await format_output(payload['final'], payload['score'], payload['iteration'])
    payload['result'] = _result
    yield payload
