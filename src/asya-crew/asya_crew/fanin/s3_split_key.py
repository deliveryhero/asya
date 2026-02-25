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

The handler reads x-asya-fan-in from the VFS at /proc/asya/msg/headers/x-asya-fan-in
(JSON-serialized by the runtime VFS). Route and non-transient headers are also
read from VFS to construct the merged message for emission.
"""

import json
import logging
import os
from contextlib import suppress

import jsonpointer


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ASYA_MSG_ROOT = os.getenv("ASYA_MSG_ROOT", "/proc/asya/msg")

_TRANSIENT_HEADERS = {
    "x-asya-fan-in",
    "x-asya-route-override",
    "x-asya-route-resolved",
    "x-asya-parent-id",
}


def _read_fan_in_header() -> dict:
    """Read and parse the x-asya-fan-in header from VFS."""
    with open(f"{ASYA_MSG_ROOT}/headers/x-asya-fan-in") as f:
        raw = f.read()
    return json.loads(raw)


def _read_route() -> dict:
    """Read route fields from VFS."""
    with open(f"{ASYA_MSG_ROOT}/route/prev") as f:
        prev_raw = f.read()
    with open(f"{ASYA_MSG_ROOT}/route/curr") as f:
        curr = f.read()
    with open(f"{ASYA_MSG_ROOT}/route/next") as f:
        next_raw = f.read()

    prev = [a for a in prev_raw.splitlines() if a] if prev_raw else []
    next_actors = [a for a in next_raw.splitlines() if a] if next_raw else []

    return {"prev": prev, "curr": curr, "next": next_actors}


def _read_non_transient_headers() -> dict:
    """Read all non-transient headers from VFS."""
    try:
        header_keys = os.listdir(f"{ASYA_MSG_ROOT}/headers")
    except (FileNotFoundError, NotADirectoryError):
        return {}

    result = {}
    for key in header_keys:
        if key in _TRANSIENT_HEADERS:
            continue
        try:
            with open(f"{ASYA_MSG_ROOT}/headers/{key}") as f:
                raw = f.read()
            try:
                result[key] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                result[key] = raw
        except FileNotFoundError:
            continue
    return result


def _read_message_id() -> str:
    """Read message id from VFS."""
    with open(f"{ASYA_MSG_ROOT}/id") as f:
        return f.read()


def aggregator(payload: dict, *, _base_dir: str = "/state/fanin") -> dict | None:
    """Fan-in aggregator handler.

    Collects N+1 messages for a single fan-out operation and emits a merged payload.
    Returns None while accumulating (runtime returns 204, sidecar routes to x-sink).
    Returns the merged payload dict when all slices arrive.

    Reads x-asya-fan-in from VFS to identify origin_id, slice_index, slice_count,
    and aggregation_key. Uses the state proxy filesystem at _base_dir for durable
    per-origin state.

    Args:
        payload: Message payload (slice content for this fan-in message)
        _base_dir: Base directory for state storage (injectable for testing)

    Returns:
        Merged parent payload with sub-agent results when complete, None while accumulating
    """
    fan_in = _read_fan_in_header()
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

    # Remove the x-asya-fan-in header so the merged message is clean
    with suppress(FileNotFoundError, OSError):
        os.remove(f"{ASYA_MSG_ROOT}/headers/x-asya-fan-in")

    # Clean up state directory after successful emission.
    # S3-backed state proxies have no real directories, so rmdir may fail
    # if the directory key has already been removed by the file deletions.
    for entry in os.listdir(base):
        os.remove(f"{base}/{entry}")
    with suppress(FileNotFoundError, OSError):
        os.rmdir(base)

    logger.info(f"[+] State cleaned up for origin_id={origin_id}")

    return merged_payload
