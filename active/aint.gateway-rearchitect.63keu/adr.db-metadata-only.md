---
title: "ADR: Database for Metadata Only (No Pub/Sub)"
status: accepted
date: 2026-04-14
---

# ADR: Database for Metadata Only (No Pub/Sub)

## Context

The current gateway uses PostgreSQL for three roles:

1. **Task state CRUD** (20-column tasks table, JSONB payload/result)
2. **Cross-process pub/sub** (pg_notify for api/mesh gateway sync)
3. **SSE replay history** (task_updates table, 24h retention)

Role 2 causes the 8KB limit, dedicated PG connection, feedback loops, and
2-second poll fallback. Role 3 adds write amplification (every progress update
persisted). Role 1 stores full payloads/results that belong in state-proxy.

## Decision

**DB stores lightweight task metadata only.** Not used for pub/sub or event
history. Real-time events delivered via in-process Go channels (SSE and mesh
callbacks colocated in same pod).

Schema:
```sql
CREATE TABLE tasks (
    id TEXT PK, parent_id TEXT, context_id TEXT,
    status TEXT, actor TEXT, progress DECIMAL(5,2),
    created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ
);
```

No JSONB columns. No task_updates table. No pg_notify.
Writes are async fire-and-forget from mesh handlers.
Reads for SSE catch-up on reconnect and dashboard list queries.
Payload/result persistence: state-proxy (S3/GCS) via x-sink.

## Consequences

- pg_notify eliminated (in-process Go channels instead)
- DB write load reduced (no JSONB, no task_updates, no per-FLY writes)
- DB could be SQLite for simple deployments, PG for larger ones
- SSE replay on reconnect reads current status from DB (not event log)
- ListTasks works (context_id + status indexes)
- Full task history via state-proxy (x-sink persists there)

## Alternatives Considered

- **Redis Pub/Sub instead of pg_notify**: another stateful system to operate,
  expensive just for ephemeral event delivery
- **NATS JetStream**: excellent fit but adds a dependency not all deployments use
- **Embedded NATS**: adds ~15MB binary size, cluster discovery complexity
- **Keep pg_notify, fix the bugs**: treats symptoms, not root cause (the split)
