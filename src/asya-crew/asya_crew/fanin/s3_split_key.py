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
"""

import json
import logging
import os

import jsonpointer


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

_TRANSIENT_HEADERS = {
    "x-asya-fan-in",
    "x-asya-route-override",
    "x-asya-route-resolved",
    "x-asya-parent-id",
}


def aggregator(envelope: dict, *, _base_dir: str = "/state/fanin") -> dict | None:
    """Fan-in aggregator handler.

    Collects N+1 messages for a single fan-out operation and emits a merged envelope.
    Returns None while accumulating (sidecar routes to x-sink silently).
    Returns merged envelope when all slices arrive.

    Args:
        envelope: Full message envelope in envelope handler mode
        _base_dir: Base directory for state storage (injectable for testing)

    Returns:
        Merged envelope when all slices collected, None while still accumulating
    """
    fan_in = envelope["headers"]["x-asya-fan-in"]
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
            json.dump(envelope["payload"], fh)
        logger.info(f"[+] Wrote slice-{idx}.json for origin_id={origin_id}")
    else:
        logger.info(f"[.] Slice-{idx}.json already exists (duplicate delivery), skipping write")

    # Index 0 carries continuation metadata: route and non-transient headers
    if idx == 0:
        msg_path = f"{base}/message.json"
        if not os.path.exists(msg_path):
            # Route is saved as-is. Runtime advances curr to next[0] when the
            # merged envelope is returned, so the aggregator's own curr position
            # is automatically shifted out.
            msg_meta = {
                "id": origin_id,
                "route": envelope["route"].copy(),
                "headers": {k: v for k, v in envelope.get("headers", {}).items() if k not in _TRANSIENT_HEADERS},
            }
            with open(msg_path, "w") as fh:
                json.dump(msg_meta, fh)
            logger.info(f"[+] Wrote message.json for origin_id={origin_id}")

    # Check completeness by counting slice files present
    entries = os.listdir(base)
    slice_files = sorted(e for e in entries if e.startswith("slice-"))

    if len(slice_files) < slice_count:
        logger.info(f"[.] Accumulating: {len(slice_files)}/{slice_count} slices for origin_id={origin_id}")
        return None  # still collecting

    # All slices arrived. Use atomic create to ensure exactly-one emission
    # across concurrent pods that may race to this point.
    sentinel_path = f"{base}/complete"
    try:
        with open(sentinel_path, "xb") as fh:
            fh.write(b"1")
    except FileExistsError:
        logger.info(f"[.] Sentinel already exists, skipping emission for origin_id={origin_id}")
        return None  # another pod already handling emission

    logger.info(f"[+] All {slice_count} slices ready, emitting merged envelope for origin_id={origin_id}")

    # Read continuation metadata (written by index-0 slice)
    msg_path = f"{base}/message.json"
    with open(msg_path) as fh:
        msg = json.load(fh)

    # Read all slices in sorted order (slice-0, slice-1, ..., slice-N)
    results = []
    for sf in slice_files:
        with open(f"{base}/{sf}") as fh:
            results.append(json.load(fh))

    # results[0] is the parent payload (slice_index=0)
    # results[1:] are sub-agent results (slice_index=1..N)
    msg["payload"] = results[0]
    jsonpointer.set_pointer(msg["payload"], fan_in["aggregation_key"], results[1:])

    # Clean up state directory after successful emission
    for entry in os.listdir(base):
        os.remove(f"{base}/{entry}")
    os.rmdir(base)

    logger.info(f"[+] State cleaned up for origin_id={origin_id}")

    return msg
