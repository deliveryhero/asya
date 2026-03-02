"""S3 split-key fan-in aggregator.

Uses a split-key storage pattern: each fan-in message writes to its own file
under {base_dir}/{origin_id}/. Completeness is detected by listing the directory.
Exactly-once emission uses atomic create (open with 'x' mode -> FileExistsError on conflict).

Requires state proxy sidecar (epic 1dmf) to be active for filesystem access.
The state proxy maps Python file I/O to an S3-backed HTTP API, so this code
works with local filesystems in tests and with S3 in production.

The x-asya-fan-in header on each incoming message contains:
    {
        "actor": "aggregator",
        "origin_id": "msg-original-abc",
        "slice_index": 0,
        "slice_count": 6,
        "aggregation_key": "/results"
    }

slice_index 0 is the parent payload; indices 1..N are sub-agent results.
aggregation_key is a JSON Pointer (RFC 6901) pointing to where the sub-agent
results list is placed inside the parent payload.

The handler reads x-asya-fan-in via the ABI yield protocol:
    fan_in = yield "GET", ".headers.x-asya-fan-in"
Before emitting the merged payload, the header is deleted:
    yield "DEL", ".headers.x-asya-fan-in"
"""

import json
import logging
import os
from collections.abc import Generator
from contextlib import suppress

import jsonpointer


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def aggregator(payload: dict, *, _base_dir: str = "/state/checkpoints/fanin") -> Generator[tuple | dict, dict, None]:
    """Fan-in aggregator handler (ABI generator).

    Collects N+1 messages for a single fan-out operation and emits a merged payload.
    When accumulating (incomplete), the generator returns without yielding a dict,
    producing 0 frames (runtime returns 204, sidecar routes to x-sink).
    When complete, yields the merged payload dict (1 frame, runtime returns 200).

    Reads x-asya-fan-in via ABI GET verb. Uses the state proxy filesystem at
    _base_dir for durable per-origin state.

    Args:
        payload: Message payload (slice content for this fan-in message)
        _base_dir: Base directory for state storage (injectable for testing)

    Yields:
        ABI protocol tuples (GET/DEL) and the merged payload dict when complete
    """
    fan_in = yield "GET", ".headers.x-asya-fan-in"
    origin_id = fan_in["origin_id"]
    idx = fan_in["slice_index"]
    slice_count = fan_in["slice_count"]
    base = f"{_base_dir}/{origin_id}"

    logger.info(f"[.] Fan-in slice {idx}/{slice_count - 1} arrived for origin_id={origin_id}")

    # Ensure state directory exists
    os.makedirs(base, exist_ok=True)

    # Write slice file (unique key per index, no contention between slices)
    slice_path = f"{base}/slice-{idx}.json"
    if not os.path.exists(slice_path):
        with open(slice_path, "w") as fh:
            json.dump(payload, fh)
        logger.info(f"[+] Wrote slice-{idx}.json for origin_id={origin_id}")
    else:
        logger.info(f"[.] Slice-{idx}.json already exists (duplicate delivery), skipping write")

    # Check completeness by counting slice files present
    entries = os.listdir(base)
    slice_files = sorted(e for e in entries if e.startswith("slice-"))

    if len(slice_files) < slice_count:
        logger.info(f"[.] Accumulating: {len(slice_files)}/{slice_count} slices for origin_id={origin_id}")
        return  # 0 frames -> runtime returns 204

    # All slices arrived. Use atomic create to ensure exactly-one emission
    # across concurrent pods that may race to this point.
    sentinel_path = f"{base}/complete"
    try:
        with open(sentinel_path, "xb") as fh:
            fh.write(b"1")
    except FileExistsError:
        logger.info(f"[.] Sentinel already exists, skipping emission for origin_id={origin_id}")
        return  # 0 frames -> runtime returns 204

    logger.info(f"[+] All {slice_count} slices ready, emitting merged payload for origin_id={origin_id}")

    # Read all slices in sorted order (slice-0, slice-1, ..., slice-N)
    results = []
    for sf in slice_files:
        with open(f"{base}/{sf}") as fh:
            results.append(json.load(fh))

    # results[0] is the parent payload (slice_index=0)
    # results[1:] are sub-agent results (slice_index=1..N)
    merged_payload = results[0]
    jsonpointer.set_pointer(merged_payload, fan_in["aggregation_key"], results[1:])

    # Strip the x-asya-fan-in header via ABI DEL verb
    yield "DEL", ".headers.x-asya-fan-in"

    # Clean up state directory after successful emission.
    # S3-backed state proxies have no real directories, so rmdir may fail
    # if the directory key has already been removed by the file deletions.
    for entry in os.listdir(base):
        os.remove(f"{base}/{entry}")
    with suppress(FileNotFoundError, OSError):
        os.rmdir(base)

    logger.info(f"[+] State cleaned up for origin_id={origin_id}")

    yield merged_payload
