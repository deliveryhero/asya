---
title: "ADR: Gateway Mesh State-Proxy Backends (pg-kv, local-kv, s3kv/gcskv positioning)"
status: accepted
date: 2026-04-23
---

# ADR: Gateway Mesh State-Proxy Backends

## Context

The mesh-api's state-proxy sidecar (`stateProxy.mesh`) needs to support multiple
storage backends. The original RFC assumed PostgreSQL (pg-kv) exclusively. During
implementation three additional backends emerged: s3kv (S3+DuckDB), gcskv
(GCS+DuckDB), and local-kv (in-memory + PVC). This ADR records the positioning
decision for each.

The key operation driving the backend choice is **FindExpired** (mesh-api
backstop, runs every ~5s): fetch all active tasks whose deadline_at has passed
and mark them failed. This is a scan+filter query over potentially thousands of
documents.

## Decision

### pg-kv — default, recommended for production

FindExpired = one SQL `WHERE deadline_at < $1 AND status != 'completed'`.
Atomic `WriteConditional` via SQL `UPDATE WHERE status = $old`. Any replica
count. Requires PostgreSQL.

**Verdict: best backend for any load and replica count.**

### local-kv — new, for low-infra single-replica deployments

Two modes: `inmem` (pure in-memory map) and `pvc` (JSON files on PVC).
FindExpired = `os.Glob` + DuckDB in-process scan of local files — microseconds,
zero network. `flock` makes `WriteConditional` truly atomic within a single
process. Zero external dependencies.

**Constraint: replicaCount MUST be 1.** In-memory state is not shared across
replicas. PVC is ReadWriteOnce. The Helm chart enforces this with a validation
error.

**Verdict: correct choice for low-infra deployments (dev, CI, single-server
prod) where Postgres is not wanted. Use pg-kv for HA.**

### s3kv / gcskv — actor state query tools, NOT gateway backends

These connectors (Go binaries backed by S3/GCS with DuckDB for /query) were
originally explored as gateway mesh state backends. They were rejected because:

1. **O(n) API cost**: FindExpired requires one S3/GCS GET per active task.
   At 1000 active tasks + 5s interval ≈ 12,000 GET requests/minute.
   pg-kv handles the same query with one SQL call.

2. **Non-atomic WriteConditional**: S3/GCS have no server-side
   read-modify-write. The saga pattern (write-then-delete across two object
   paths) has a TOCTOU window. pg-kv uses SQL `WHERE` for true atomicity.

3. **Goroutine starvation under load**: if FindExpired takes longer than the
   mesh-api's HTTP client timeout (e.g., 100+ active tasks → multiple seconds
   of parallel S3 GETs), mesh-api goroutines accumulate waiting for responses,
   eventually blocking the readiness probe. The problem was mitigated with
   `maxFetchKeys=1000` and a 30s independent context, but it's an inherent
   architectural mismatch.

**Correct positioning for s3kv/gcskv:** actor state analytics. Actors persist
execution results as JSON objects in S3/GCS. Users query historical messages —
content, timing, status — for debugging and analytics. DuckDB enables arbitrary
Mango-style queries over these objects. The connector is schema-agnostic (no
active/archive partitioning baked in; that's the actor's concern).

Example: image generation pipeline writes `{bucket}/run-{id}/result.json`.
Analytics: `POST /query {"filter": {"model": "sdxl", "steps": {"$gt": 50}}}`.

**Verdict: useful for actor state queries, not suitable for gateway mesh state.**

## E2E Profile Naming

Profile names encode the gateway state backend to make the test matrix explicit:

| Profile | Transport | Actor storage | Gateway state |
|---|---|---|---|
| `pubsub-gcs-pg` | Pub/Sub | GCS | pg-kv |
| `sqs-s3-pg` | SQS | S3 | pg-kv |
| `sqs-s3-pvc` | SQS | S3 | local-kv (pvc mode) |

## Consequences

- s3kv/gcskv are kept in the codebase as actor state tools; the DuckDB /query
  bugs fixed during this work (read_text, context timeout, maxFetchKeys, doc
  cache) remain valuable for that use case.
- local-kv is a new binary in `asya-state-proxy-go` (no new Docker image;
  selected via `command: ["/local-kv"]` override in the Helm chart).
- The `sqs-s3-pvc` E2E profile validates a zero-database gateway deployment.
- Python state proxy connectors (s3_buffered_lww, gcs_buffered_lww, etc.) will
  gain a `/query` endpoint via python-duckdb (tracked separately), enabling
  analytics queries from Python actor pipelines.

## Alternatives Considered

- **S3/GCS with active/archive partitioning**: routes terminal tasks to an
  `archive/` prefix so FindExpired only scans `active/`. Reduces scan scope
  dramatically but adds saga-pattern non-atomicity (two-object write is never
  atomic in S3/GCS), complex routing logic, and still has per-task GET costs.
  Rejected: too much complexity for a backend that is architecturally mismatched.
- **DynamoDB / Bigtable**: atomic CAS via conditional writes; better than S3/GCS
  for operational state. Future option; out of scope for current implementation.
