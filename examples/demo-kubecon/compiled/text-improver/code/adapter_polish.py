# fmt: off
# ruff: noqa
"""Auto-generated adapter for polish"""
from actors import polish

async def adapter_polish(payload: dict):
    """Adapter: wraps polish() for dict-in/dict-out protocol"""
    _result = await polish(payload['draft'])
    payload['final'] = _result
    yield payload
