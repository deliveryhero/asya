---
title: "Phase 6: S3 state-proxy with DuckDB query (high-latency alternative)"
status: open
priority: 2 # medium
dependencies:
  - 9bb3j
---

S3 state-proxy connector for envelope metadata (alternative to PG for high-latency deployments). Uses DuckDB for /query support over S3-stored JSON documents.

Use case: deployments that don't want to run PostgreSQL. Messages stored as JSON files in S3. DuckDB (embedded, in-process) provides query capabilities.

Implementation:
- Extend existing S3 buffered LWW connector with /query support
- DuckDB Go driver (go-duckdb, maintained by DuckDB team, 1.1k stars)
- On /query: DuckDB reads JSON from S3, applies filter/sort/limit
- Caching: DuckDB can cache recently accessed objects
- Key pattern: s3://{bucket}/mesh/msg/{id}.json
- Expression indexes: not applicable (DuckDB scans on query)

Performance:
- <10K messages: sub-second queries (acceptable for low-frequency deployments)
- >10K messages: consider PG connector instead
- Write latency: S3 PUT (~50ms) — acceptable for high-latency workloads (ML training)

Testing:
- Unit: DuckDB query translation
- Component: Docker Compose with MinIO, test KV + query
- E2E: Kind cluster with S3 state-proxy, test full mesh-api flow

Depends on: 9bb3j (PG connector, for interface compatibility)
