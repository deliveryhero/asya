# fmt: off
# ruff: noqa
"""Auto-generated adapter for get_weather"""

async def adapter_get_weather(payload: dict):
    """Adapter: wraps get_weather() for dict-in/dict-out protocol"""
    _result = await get_weather(payload['city'])
    payload['weather'] = _result
    yield payload
