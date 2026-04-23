---
title: "PR5+PR7: S3/GCS actor-state query connector (DuckDB /query) + gateway chart backends"
status: pushed
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - gateway-rearchitect
  - pr:457
  - pr:458
  - branch:gateway-rearchitect/i0ewl.s3-kv-duckdb
dependencies:
  - 9bb3j
---

## Scope (two PRs, owned together)

**PR #457** — asya-gateway Helm chart: configurable `stateProxy.mesh.backend`
(pg-kv | s3kv | gcskv | s3 | gcs). All Go binaries ship in one
`asya-state-proxy-go` image; binary selected by `command:` override.

**PR #458** — s3kv + gcskv Go connectors (S3+DuckDB, GCS+DuckDB).
Also includes gcskv (GCS+DuckDB, PR #461 merged in).

## Repositioning: s3kv/gcskv are actor-state query tools, NOT gateway backends

**Why not gateway mesh state:**
FindExpired needs O(n) S3 GETs per cycle (one per active task).
At 1000 active tasks + 5s interval ≈ 12,000 GETs/min — expensive and slow.
pg-kv answers the same query with one SQL WHERE clause.

**Correct use case — actor state analytics:**
Actors persist results/outputs to S3/GCS at pipeline end. Users query
historical messages for analytics and debugging via Mango filter on DuckDB.
The connector is **schema-agnostic** (no active/archive schema baked in;
partitioning is the actor's concern, not the connector's).

Example: image generation pipeline writes `{bucket}/run-123/result.json`.
Downstream analytics actor calls `POST /query {"filter": {"model": "sdxl",
"status": "done"}}` to find all completed jobs across runs.

## DuckDB bugs fixed in PR #458

1. `duckdb.Map` type: `read_json_auto` maps nested JSON → `duckdb.Map`,
   not serializable. Fixed: `read_text` + `json_extract_string(content, '$.field')`.
2. Context cancellation: mesh-api's short FindExpired deadline canceled S3 GETs
   mid-flight. Fixed: independent `context.WithTimeout(Background, 30s)`.
3. `maxFetchKeys=1000` + rotating cursor: bounded per-call latency; all keys
   seen over time (50s full sweep at 10k active tasks).
4. Document-level TTL cache (4s): avoids redundant S3 GETs for stable tasks.

## E2E profiles (naming reflects gateway state backend)

- `pubsub-gcs-pg` — Pub/Sub + GCS actor state + **pg-kv** gateway mesh state
- `sqs-s3-pg`    — SQS + S3 actor state + **pg-kv** gateway mesh state (current)

The `sqs-s3-pvc` profile (SQS + S3 + local-kv gateway) is tracked under the
new aint for local-kv.

## Follow-up: Python /query (Aint A)

Add `/query` to Python actor state proxies (s3_buffered_lww, gcs_buffered_lww,
etc.) via `python-duckdb`. DuckDB httpfs reads S3/GCS directly — no temp
copies. New optional extra: `"query" = ["duckdb>=0.10"]`.

See plan.md for full execution plan.
