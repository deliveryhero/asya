# fmt: off
# ruff: noqa
"""Auto-generated adapter for web_search"""

async def adapter_web_search(payload: dict):
    """Adapter: wraps web_search() for dict-in/dict-out protocol"""
    _result = await web_search(payload['tool_args']['query'])
    payload['tool_result'] = _result
    yield payload
