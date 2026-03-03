---
title: Migrate s3 persister to checkpointer actor crew
priority: 2 # medium
type: task
tags:
  - worktree:.worktrees/debt/1k34nz.migrate-s3-persister-checkpointer-actor-crew
  - branch:debt/1k34nz.migrate-s3-persister-checkpointer-actor-crew
  - pr:216
---




## Summary

Replace the direct `boto3` S3 client in `src/asya-crew/asya_crew/message_persistence/s3.py` with a generic checkpointer that writes through the **state proxy** file I/O interface. The checkpointer reads message metadata from the VFS (`/proc/asya/msg/`) and writes the message as JSON to a mounted state path — no storage SDK imports needed.

## Current State

- `checkpoint_handler` in `s3.py` initializes a `boto3.client("s3")` at module load time
- Reads VFS metadata: `/proc/asya/msg/id`, `/proc/asya/msg/status/phase`, `/proc/asya/msg/route/prev`
- Constructs S3 key: `{phase_prefix}/{timestamp}/{actor}/{id}.json`
- Calls `s3_client.put_object()` directly
- Env vars: `ASYA_S3_BUCKET`, `ASYA_S3_ENDPOINT`, `ASYA_S3_ACCESS_KEY`, `ASYA_S3_SECRET_KEY`

## Target State

- **New file**: `src/asya-crew/asya_crew/checkpointer.py` (replaces `message_persistence/s3.py`)
- Reads the same VFS metadata (`/proc/asya/msg/id`, `status/phase`, `route/prev`)
- Constructs the same structured path: `{phase_prefix}/{timestamp}/{actor}/{id}.json`
- Writes via standard `open()` on the state proxy mount path (e.g., `/state/checkpoints/...`)
- **Zero storage SDK imports** — the state proxy connector sidecar handles the actual backend
- Backend selection is entirely driven by the `stateProxy` config in the AsyncActor CRD

## What Changes

1. **`checkpoint_handler`**: Replace `s3_client.put_object()` with `open(f"{mount_path}/{key}", "w")` + `f.write(json.dumps(payload))`
2. **Env vars**: Replace `ASYA_S3_*` vars with `ASYA_CHECKPOINT_MOUNT` (default: `/state/checkpoints`)
3. **Module-level init**: Remove `boto3` import and S3 client initialization
4. **`ensure_bucket_exists`**: Remove entirely (state proxy connector handles backend setup)
5. **x-sink hooks config**: Update `ASYA_SINK_HOOKS` default or docs to reference new handler path
6. **Tests**: Update unit tests to mock file I/O instead of boto3
7. **Helm chart**: Update asya-crew chart to configure `stateProxy` mount for the checkpointer connector

## Example AsyncActor CRD (post-migration)

```yaml
spec:
  stateProxy:
    - name: checkpoints
      mount:
        path: /state/checkpoints
      writeMode: buffered
      connector:
        image: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0
        env:
          - name: STATE_BUCKET
            value: my-checkpoints-bucket
```

Switching to GCS or PostgreSQL is just a connector image swap — checkpointer code unchanged.

## Out of Scope

- New state proxy connectors (GCS, PostgreSQL) — separate tasks
- Changes to the VFS layout
- Changes to x-sink routing logic (stays in `sink.py`)
