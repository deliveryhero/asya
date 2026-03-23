# fmt: off
# ruff: noqa
"""Auto-generated adapter for list_gcs_files"""

async def adapter_list_gcs_files(payload: dict):
    """Adapter: wraps list_gcs_files() for dict-in/dict-out protocol"""
    _result = await list_gcs_files(payload['tool_args']['bucket'], payload['tool_args']['prefix'])
    payload['tool_result'] = _result
    yield payload
