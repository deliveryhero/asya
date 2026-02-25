"""Component tests: streaming behavior for state proxy connectors."""

import base64
import os
import uuid

import pytest


def _key():
    return f"stream-{uuid.uuid4().hex[:8]}.bin"


class TestLargeFileStreaming:
    """Test streaming of large files."""

    def test_write_and_read_1mb(self, runtime):
        key = _key()
        data = os.urandom(1 * 1024 * 1024)
        encoded = base64.b64encode(data).decode()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": encoded, "mode": "wb"})

        result = runtime.invoke({"op": "read", "path": f"/state/meta/{key}", "mode": "rb"})
        read_back = base64.b64decode(result["content_b64"])
        assert len(read_back) == len(data)
        assert read_back == data

    def test_stat_after_large_write(self, runtime):
        key = _key()
        size = 512 * 1024
        data = base64.b64encode(os.urandom(size)).decode()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": data, "mode": "wb"})

        result = runtime.invoke({"op": "stat", "path": f"/state/meta/{key}"})
        assert result["size"] == size

    def test_multiple_sequential_writes(self, runtime):
        """Write multiple files sequentially, verify all readable."""
        keys = [_key() for _ in range(5)]
        for i, key in enumerate(keys):
            content = f"file-{i}-" + "x" * 1000
            runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": content})

        for i, key in enumerate(keys):
            result = runtime.invoke({"op": "read", "path": f"/state/meta/{key}"})
            assert result["content"].startswith(f"file-{i}-")
