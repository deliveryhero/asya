"""Component tests: CAS connector behavior."""

import uuid

import pytest


def _key():
    return f"cas-{uuid.uuid4().hex[:8]}.txt"


class TestCASBehavior:
    """Verify CAS connectors handle sequential writes correctly."""

    @pytest.fixture(autouse=True)
    def _skip_non_cas(self, connector_profile):
        if connector_profile not in ("s3-cas", "redis-cas"):
            pytest.skip(f"CAS tests only run with CAS profiles, got {connector_profile}")

    def test_sequential_writes_succeed(self, runtime):
        """Two sequential writes to the same key should both succeed."""
        key = _key()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "v1"})
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "v2"})
        result = runtime.invoke({"op": "read", "path": f"/state/meta/{key}"})
        assert result["content"] == "v2"

    def test_read_write_read_cycle(self, runtime):
        """Read-write-read cycle should work without false conflicts."""
        key = _key()
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "initial"})
        runtime.invoke({"op": "read", "path": f"/state/meta/{key}"})
        runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "updated"})
        result = runtime.invoke({"op": "read", "path": f"/state/meta/{key}"})
        assert result["content"] == "updated"

    def test_multiple_read_write_cycles(self, runtime):
        """Multiple read-write cycles on the same key should all succeed."""
        key = _key()
        for i in range(5):
            if i > 0:
                runtime.invoke({"op": "read", "path": f"/state/meta/{key}"})
            runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": f"v{i}"})

        result = runtime.invoke({"op": "read", "path": f"/state/meta/{key}"})
        assert result["content"] == "v4"

    def test_write_new_key_no_prior_read(self, runtime):
        """Writing a never-read key should succeed (unconditional write)."""
        key = _key()
        result = runtime.invoke({"op": "write", "path": f"/state/meta/{key}", "content": "new"})
        assert result["written"] == 3
