---
title: "PR6: pvc-kv — low-infra gateway state proxy (in-memory + PVC, DuckDB /query)"
status: working
slug: pvc-kv
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - gateway-rearchitect
  - pr:new
dependencies:
  - i0ewl
---

New `cmd/local-kv` Go binary: gateway mesh state proxy with zero external
infrastructure. Two modes — inmem (no persistence) and pvc (JSON files on PVC).
Both require `replicaCount: 1` (enforced by chart validation).

DuckDB reads local files directly → FindExpired = os.Glob + in-process scan,
no network. File locking (`flock`) makes WriteConditional truly atomic.

Active/archive partitioning is opt-in config, not hardcoded:
`LOCAL_KV_PARTITION=true`, `LOCAL_KV_ARCHIVE_STATUSES=completed,failed,canceled`.

New E2E profile `sqs-s3-pvc`: SQS + S3 actor state + local-kv gateway.
No Postgres required. Existing profiles renamed to reflect gateway backend:
`pubsub-gcs` → `pubsub-gcs-pg`, `sqs-s3` → `sqs-s3-pg`.

See plan.md for full implementation plan.
