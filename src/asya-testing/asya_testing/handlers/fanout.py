"""Fan-out router test handler.

Generates N+1 fan-out slices from a payload containing a 'topics' list.
This handler still uses the VFS (/proc/asya/msg/) to control routing and is
pending migration to the ABI yield protocol.

Generator protocol for fan-out with per-slice routing:
  Before each yield, writes VFS route/next and headers/x-asya-fan-in.
  The runtime snapshots state after each yield to build the frame route.
  The sidecar uses the frame route to dispatch each slice independently.

Slice 0 (index 0): parent payload, routed directly to aggregator.
Slices 1..N (index 1..N): topic payloads, routed to sub-agent -> aggregator.
"""

import json
import os
from collections.abc import Generator


ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")

ASYA_ACTOR_SUB_AGENT = os.getenv("ASYA_ACTOR_SUB_AGENT", "test-sub-agent")
ASYA_ACTOR_AGGREGATOR = os.getenv("ASYA_ACTOR_AGGREGATOR", "test-aggregator")
ASYA_FANIN_AGGREGATION_KEY = os.getenv("ASYA_FANIN_AGGREGATION_KEY", "/results")


def _read_msg_id() -> str:
    """Read message id from VFS."""
    with open(f"{ASYA_MSG_ROOT}/id") as f:
        return f.read()


def fanout_router_handler(payload: dict) -> Generator[dict, None, None]:
    """Fan-out router: generates N+1 slices from payload['topics'].

    Reads origin_id from VFS. Uses VFS to set per-slice routing (route/next)
    and x-asya-fan-in header before each yield.

    Slice 0: parent payload -> aggregator (route/next = ["aggregator"])
    Slices 1..N: topic payload -> sub-agent -> aggregator
                 (route/next = ["sub-agent", "aggregator"])

    Args:
        payload: Input payload containing 'topics' list

    Yields:
        dict: Slice payload for each fan-out message
    """
    topics = payload.get("topics", [])
    origin_id = _read_msg_id()

    slice_count = 1 + len(topics)

    def make_fan_in_header(idx: int) -> str:
        return json.dumps(
            {
                "actor": ASYA_ACTOR_AGGREGATOR,
                "origin_id": origin_id,
                "slice_index": idx,
                "slice_count": slice_count,
                "aggregation_key": ASYA_FANIN_AGGREGATION_KEY,
            }
        )

    # Slice 0: parent payload -> aggregator directly
    with open(f"{ASYA_MSG_ROOT}/route/next", "w") as f:
        f.write(ASYA_ACTOR_AGGREGATOR)
    with open(f"{ASYA_MSG_ROOT}/headers/x-asya-fan-in", "w") as f:
        f.write(make_fan_in_header(0))

    yield dict(payload)

    # Slices 1..N: each topic -> sub-agent -> aggregator
    for i, topic in enumerate(topics, start=1):
        with open(f"{ASYA_MSG_ROOT}/route/next", "w") as f:
            f.write(f"{ASYA_ACTOR_SUB_AGENT}\n{ASYA_ACTOR_AGGREGATOR}")
        with open(f"{ASYA_MSG_ROOT}/headers/x-asya-fan-in", "w") as f:
            f.write(make_fan_in_header(i))

        yield {"topic": topic, "_slice_index": i}
