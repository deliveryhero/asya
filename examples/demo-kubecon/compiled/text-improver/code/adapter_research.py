# fmt: off
# ruff: noqa
"""Auto-generated adapter for research"""
from actors import research

async def adapter_research(payload: dict):
    """Adapter: wraps research() for dict-in/dict-out protocol"""
    _result = await research(payload['topic'])
    payload['context'] = _result
    yield payload
