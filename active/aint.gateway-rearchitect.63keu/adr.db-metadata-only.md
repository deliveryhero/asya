---
title: "ADR: PG State-Proxy as Document Store (No Typed Schema)"
status: accepted
date: 2026-04-16
supersedes: "ADR: Database for Metadata Only (No Pub/Sub)"
---

# ADR: PG State-Proxy as Document Store

## Context

The mesh-api needs a database for message metadata. Options considered:
1. Direct PG with typed columns + Alembic migrations
2. Direct PG with JSONB + MessageStore Go interface
3. PG via state-proxy connector (document store over JSONB)

The project already has a state-proxy architecture (sidecar connectors for
S3/GCS/Redis). Extending it to PostgreSQL creates a universal storage
abstraction reusable across the platform.

## Decision

**Use a PG state-proxy connector as the mesh-api's database.** The mesh-api
talks to the state-proxy via HTTP over Unix socket. Zero SQL in the mesh-api.

Schema (one table, never changes):
```sql
CREATE TABLE IF NOT EXISTS kv (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kv_gin ON kv USING gin (value jsonb_path_ops);
```

All message fields (status, actor, progress, context_id, trace_id, parent_id,
deadline_at, error, message) stored in the JSONB `value` column. No typed
columns. No Alembic. No migrations.

Expression indexes for hot fields configured via env var:
```bash
STATE_PROXY_PG_INDEXES: "status, (deadline_at)::timestamptz"
```
Connector auto-creates indexes on startup (`CREATE INDEX CONCURRENTLY`).
Lock-free, safe on live tables.

The /query endpoint supports Mango-style filter DSL (filter/sort/limit/offset)
translated to parameterized SQL.

## Consequences

- Zero SQL in mesh-api Go code. No PG driver dependency.
- Same state-proxy interface as S3/GCS/Redis connectors (swappable).
- No Alembic, no schema migrations, ever.
- JSONB storage ~2x overhead vs typed columns (~100 bytes/row, negligible).
- Expression indexes from env vars give B-tree query performance.
- Future: DuckDB connector for S3 analytical queries, DynamoDB connector,
  MongoDB connector -- all implement the same interface.
- Go PG connector can also be compiled as in-process library for zero-overhead
  mode (financial/low-latency workloads).

## Alternatives Considered

- **Typed columns + Alembic**: optimal storage/query but requires migrations,
  locks the DB to a specific schema, hard to port to NoSQL.
- **Go MessageStore + PgStore**: same effort (~300 LOC Go) but Go-specific,
  not reusable by Python services or future Rust services.
- **Generated columns**: auto-extract from JSONB to typed columns. Elegant but
  ALTER TABLE locks the table for existing rows. Expression indexes achieve
  the same query performance without table locks.
