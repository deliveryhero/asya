"""Integration tests: stateful actors in full sidecar pipeline."""

import uuid


def _msg_id() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


SINK_QUEUE = "asya-default-x-sink"
SUMP_QUEUE = "asya-default-x-sump"
STATE_OPS_QUEUE = "asya-default-test-state-ops"
ECHO_QUEUE = "asya-default-test-plain-echo"


class TestStatefulActorPipeline:
    """Tests for an actor with state proxy mounts in a full pipeline."""

    def test_write_and_read_state_across_messages(self, transport):
        """Write state in one message, read it back in another."""
        key = f"test-{uuid.uuid4().hex[:8]}.txt"
        content = "hello from integration test"

        # Message 1: write state
        write_msg = {
            "id": _msg_id(),
            "route": {"prev": [], "curr": "test-state-ops", "next": []},
            "payload": {"op": "write", "path": f"/state/meta/{key}", "content": content},
        }
        transport.publish_message(STATE_OPS_QUEUE, write_msg)
        result = transport.assert_message_in_queue(SINK_QUEUE, timeout=15)
        assert result["payload"]["written"] == len(content)

        # Message 2: read state back
        read_msg = {
            "id": _msg_id(),
            "route": {"prev": [], "curr": "test-state-ops", "next": []},
            "payload": {"op": "read", "path": f"/state/meta/{key}"},
        }
        transport.publish_message(STATE_OPS_QUEUE, read_msg)
        result = transport.assert_message_in_queue(SINK_QUEUE, timeout=15)
        assert result["payload"]["content"] == content

    def test_state_persists_across_multiple_messages(self, transport):
        """Write multiple keys, then list them to verify persistence."""
        prefix = f"persist-{uuid.uuid4().hex[:6]}"
        keys = [f"{prefix}/a.txt", f"{prefix}/b.txt", f"{prefix}/c.txt"]

        for key in keys:
            msg = {
                "id": _msg_id(),
                "route": {"prev": [], "curr": "test-state-ops", "next": []},
                "payload": {"op": "write", "path": f"/state/meta/{key}", "content": key},
            }
            transport.publish_message(STATE_OPS_QUEUE, msg)
            transport.assert_message_in_queue(SINK_QUEUE, timeout=15)

        # List directory
        list_msg = {
            "id": _msg_id(),
            "route": {"prev": [], "curr": "test-state-ops", "next": []},
            "payload": {"op": "listdir", "path": f"/state/meta/{prefix}"},
        }
        transport.publish_message(STATE_OPS_QUEUE, list_msg)
        result = transport.assert_message_in_queue(SINK_QUEUE, timeout=15)
        entries = result["payload"]["entries"]
        assert "a.txt" in entries
        assert "b.txt" in entries
        assert "c.txt" in entries

    def test_read_missing_key_routes_to_sump(self, transport):
        """Reading a non-existent key causes an error routed to x-sump."""
        msg = {
            "id": _msg_id(),
            "route": {"prev": [], "curr": "test-state-ops", "next": []},
            "payload": {"op": "read", "path": "/state/meta/nonexistent-integration.txt"},
        }
        transport.publish_message(STATE_OPS_QUEUE, msg)
        result = transport.assert_message_in_queue(SUMP_QUEUE, timeout=15)
        assert result["payload"]["error"] == "processing_error"

    def test_overwrite_state(self, transport):
        """Overwrite a key and verify new content."""
        key = f"test-{uuid.uuid4().hex[:8]}.txt"

        # Write initial
        transport.publish_message(
            STATE_OPS_QUEUE,
            {
                "id": _msg_id(),
                "route": {"prev": [], "curr": "test-state-ops", "next": []},
                "payload": {"op": "write", "path": f"/state/meta/{key}", "content": "first"},
            },
        )
        transport.assert_message_in_queue(SINK_QUEUE, timeout=15)

        # Overwrite
        transport.publish_message(
            STATE_OPS_QUEUE,
            {
                "id": _msg_id(),
                "route": {"prev": [], "curr": "test-state-ops", "next": []},
                "payload": {"op": "write", "path": f"/state/meta/{key}", "content": "second"},
            },
        )
        transport.assert_message_in_queue(SINK_QUEUE, timeout=15)

        # Read back
        transport.publish_message(
            STATE_OPS_QUEUE,
            {
                "id": _msg_id(),
                "route": {"prev": [], "curr": "test-state-ops", "next": []},
                "payload": {"op": "read", "path": f"/state/meta/{key}"},
            },
        )
        result = transport.assert_message_in_queue(SINK_QUEUE, timeout=15)
        assert result["payload"]["content"] == "second"


class TestBackwardCompatibility:
    """Tests that actors without state proxy work unchanged."""

    def test_echo_actor_without_state_mounts(self, transport):
        """Plain echo actor processes messages without state proxy."""
        msg = {
            "id": _msg_id(),
            "route": {"prev": [], "curr": "test-plain-echo", "next": []},
            "payload": {"message": "no state needed"},
        }
        transport.publish_message(ECHO_QUEUE, msg)
        result = transport.assert_message_in_queue(SINK_QUEUE, timeout=15)
        assert result["payload"]["echoed"] == "no state needed"
