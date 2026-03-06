# Crew Checkpointer

## Overview

The checkpointer (`src/asya-crew/asya_crew/checkpointer.py`) persists complete
messages (metadata + payload) as JSON files via the state proxy filesystem
abstraction. The storage backend is pluggable — S3, GCS, or any backend
supported by the state proxy connector configured in the AsyncActor CRD.

The checkpointer is called from the `x-sink` and `x-sump` crew actors. It
receives message metadata (id, phase, route) as keyword arguments and writes
the full envelope as JSON.

---

## Key Design

### Storage Backend

The checkpointer writes through the state proxy mount, not directly to cloud
storage. The mount path is configured via `ASYA_PERSISTENCE_MOUNT`. The state
proxy connector sidecar (S3, GCS, etc.) transparently syncs writes to the
configured backend.

This keeps the checkpointer backend-agnostic: the same Python code works for
S3, GCS, NATS, Redis, or any future connector that implements the state proxy
interface.

### Key Pattern

Files are stored at `{mount}/{prefix}/{id}.json`:

| `status.phase`   | `prefix`     | Example key               |
|------------------|-------------|---------------------------|
| `succeeded`      | `succeeded` | `succeeded/msg-123.json`  |
| `failed`         | `failed`    | `failed/msg-456.json`     |
| (mid-pipeline)   | `checkpoint`| `checkpoint/msg-789.json` |

The flat `{prefix}/{id}.json` pattern is chosen because the gateway already
knows the task ID (= message ID) and the final status. It can reconstruct
the object key without querying any index — no DB column or header needed for
lookup.

**Message IDs are sanitized with `os.path.basename()` before use in paths** to
prevent path traversal attacks (e.g., a crafted ID like `../../etc/passwd`).

The actor name and timestamp are preserved inside the JSON body
(`route.prev`, `status.phase`) for debugging and analytics.

### JSON Schema

```json
{
  "id": "<message-id>",
  "parent_id": "<parent-id>",   // omitted if empty (fanout child only)
  "route": {
    "prev": ["actor-a", "actor-b"],
    "curr": "x-sink"
  },
  "status": { "phase": "succeeded" },  // omitted if no phase
  "payload": { ... }
}
```

---

## Deployment

The checkpointer is part of the `asya-crew` image and deployed via the
`deploy/helm-charts/asya-crew` Helm chart. It is activated by setting
`ASYA_PERSISTENCE_MOUNT` in the crew actor's environment.

### State Proxy Overlay

Persistence is wired through an `EnvironmentConfig` overlay that adds a state
proxy sidecar to the crew actor pods. The overlay configures:

- `spec.stateProxy.connector.image` — backend-specific connector image
  (e.g., `asya-state-proxy-s3-buffered-lww`, `asya-state-proxy-gcs-buffered-lww`)
- `spec.stateProxy.mount.path` — filesystem path visible to the checkpointer
- Backend-specific env vars (bucket, endpoint, credentials) passed to the connector

Example crew chart snippet for the GCS profile:

```yaml
crew:
  persistence:
    enabled: true
    backend: gcs
    config:
      bucket: asya-results
      project: my-gcp-project
    connector:
      image: ghcr.io/deliveryhero/asya-state-proxy-gcs-buffered-lww:latest
  x-sink:
    env:
      ASYA_PERSISTENCE_MOUNT: "/state/checkpoints/results"
```

### Graceful Skip

If `ASYA_PERSISTENCE_MOUNT` is not set, the checkpointer logs a debug message
and returns immediately. This allows the crew actors to run in environments
without persistence configured (e.g., lightweight test setups).

---

## Testing

Unit tests live in `src/asya-crew/tests/test_checkpointer.py`.

Coverage:

| Test | What it verifies |
|------|-----------------|
| `test_succeeded_phase_uses_succeeded_prefix` | Phase routing to `succeeded/` prefix |
| `test_failed_phase_uses_failed_prefix` | Phase routing to `failed/` prefix |
| `test_missing_phase_uses_checkpoint_prefix` | Empty phase → `checkpoint/` prefix |
| `test_completes_without_error` | Handler completes without raising |
| `test_skips_when_mount_not_configured` | Graceful skip when env var absent |
| `test_key_is_flat_prefix_and_id` | Key is exactly `{prefix}/{id}.json` |
| `test_persists_complete_message` | Full JSON structure (id, route, status, payload) |
| `test_message_without_parent_id` | `parent_id` omitted when empty |
| `test_raises_on_non_dict_payload` | `ValueError` on non-dict payload |

Run with:

```bash
make -C src/asya-crew test-unit
```

---

## Future: DuckDB OLAP Queries

Data scientists can query historical checkpointed messages using DuckDB over
the object store. The flat `{prefix}/{id}.json` structure is scannable, but
date-partitioned keys would enable more efficient glob queries.

### Proposed Future Key Pattern

```
{prefix}/{YYYY-MM-DD}/{id}.json
```

Example:

```
succeeded/2026-03-06/msg-123.json
failed/2026-03-06/msg-456.json
```

This enables DuckDB queries scoped by date:

```sql
SELECT *
FROM read_json_auto('s3://asya-results/succeeded/2026-03-06/*.json')
WHERE json_extract_string(payload, '$.model') = 'sdxl'
```

### Gateway Reconstruction

With date-partitioned keys, the gateway needs the date to reconstruct the key.
The proposed algorithm:

1. When the `x-sink`/`x-sump` actor checkpoints a message, it emits a
   progress report to the gateway via ABI `FLY` or HTTP — including the
   relative key `{prefix}/{YYYY-MM-DD}/{id}.json` as an envelope header
   (`x-asya-checkpoint-key`).
2. The sidecar's progress reporter carries this header in the status update
   to the gateway.
3. The gateway stores the key in a `tasks.checkpoint_key` DB column.
4. `GetTask` reads `checkpoint_key` and returns or fetches the artifact.

This keeps the key derivable without modifying the XRD or adding new
infrastructure. The date can alternatively be derived from
`tasks.updated_at::date`, eliminating the need for the sidecar to carry the
key — the gateway reconstructs it as `{status}/{tasks.updated_at::date}/{id}.json`.

### Implementation Status

⚠️ Not yet implemented. The current key pattern is `{prefix}/{id}.json`.
Date partitioning is planned as a follow-up when DuckDB OLAP use cases are
confirmed.
