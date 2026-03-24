# fmt: off
# ruff: noqa
"""Auto-generated adapter for generate"""
from actors import generate

async def adapter_generate(payload: dict):
    """Adapter: wraps generate() for dict-in/dict-out protocol"""
    _result = await generate(payload['topic'], payload['context'])
    payload['result'] = _result
    yield payload
