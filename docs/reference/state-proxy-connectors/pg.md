---
description: "PostgreSQL connector (Go): JSONB document store with Mango-style queries for gateway mesh-api envelope state"
---

# PostgreSQL Connector

A Go-based state proxy connector that stores key-value pairs in a PostgreSQL
JSONB table. Unlike the Python connectors (which back actor `/state/` file I/O),
this connector serves as the persistence layer for the `asya-mesh-api` binary —
storing envelope metadata, status, and payload data.

**Source**: `src/asya-state-proxy/go/`

## Architecture

```
mesh-api  ──HTTP/Unix socket──►  state-proxy-pg  ──pgx──►  PostgreSQL
(port 8080/8081)                  (CONNECTOR_SOCKET)         (kv table)
```

The connector runs as a sidecar in the same pod as `asya-mesh-api`, sharing a
Unix socket via an `emptyDir` volume. The mesh-api binary never connects to
PostgreSQL directly — all persistence goes through the state-proxy HTTP API.

## Storage Schema

Single table, no migrations:

```sql
CREATE TABLE IF NOT EXISTS kv (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kv_gin ON kv USING gin (value jsonb_path_ops);
```

Expression indexes are created at startup from the `STATE_PROXY_PG_INDEXES`
environment variable.

## HTTP API

Same KV protocol as the Python connectors, plus a `/query` endpoint:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Health check |
| `GET` | `/keys/{key}` | Read a key |
| `PUT` | `/keys/{key}` | Write (upsert) a key |
| `PUT` | `/keys/{key}?if_status={s}` | Conditional write (CAS on status field) |
| `HEAD` | `/keys/{key}` | Check existence |
| `DELETE` | `/keys/{key}` | Delete a key |
| `GET` | `/keys/?prefix={p}` | List keys by prefix |
| `POST` | `/query` | Mango-style filter query |

### Conditional Writes

The `?if_status=` query parameter enables atomic compare-and-set on the JSONB
`status` field. The connector executes:

```sql
UPDATE kv SET value = $2, updated_at = now()
WHERE key = $1 AND value->>'status' = $3
```

Returns `409 Conflict` if the current status doesn't match (another writer
advanced it concurrently).

### Query Endpoint

`POST /query` accepts a Mango-style filter DSL:

```json
{
  "prefix": "msg/",
  "filter": {"status": "running", "progress": {"$gt": 50}},
  "sort": ["-created_at"],
  "limit": 10,
  "offset": 0,
  "count": false
}
```

Supported operators: `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`,
`$exists`, `$contains`. Field names are validated against `^[a-zA-Z_][a-zA-Z0-9_]*$`
to prevent SQL injection.

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `CONNECTOR_SOCKET` | Unix socket path | Yes |
| `STATE_PROXY_PG_URL` | PostgreSQL connection string | Yes |
| `STATE_PROXY_PG_INDEXES` | Comma-separated expression index specs | No |

### Index Specification

`STATE_PROXY_PG_INDEXES` accepts two forms:

- Simple field: `status` → `CREATE INDEX idx_kv_expr_status ON kv ((value->>'status'))`
- Cast expression: `(deadline_at)::timestamptz` → `CREATE INDEX idx_kv_expr_deadline_at ON kv (((value->>'deadline_at')::timestamptz))`

Example: `STATE_PROXY_PG_INDEXES=status,(deadline_at)::timestamptz`

## Testing

Unit tests (no PG required):
```bash
cd src/asya-state-proxy/go && go test ./...
```

Integration tests (requires PG — set `STATEPROXY_PG_TEST_URL`):
```bash
STATEPROXY_PG_TEST_URL=postgres://postgres:postgres@localhost:5432/test \
  go test ./internal/pg/ -v -run TestConnector
```

Component tests (Docker Compose with PG + SQS + mesh-api):
```bash
make -C testing/component/mesh-api test
```

## Differences from Python Connectors

| Aspect | Python connectors | PG connector (Go) |
|--------|-------------------|-------------------|
| Language | Python | Go |
| Consumer | Actor runtime (file I/O interception) | mesh-api binary (HTTP client) |
| Storage | Object stores (S3, GCS), Redis | PostgreSQL JSONB |
| Query | Key prefix listing only | Mango-style filter DSL |
| Consistency | LWW or CAS (ETag/generation/WATCH) | Monotonic status ordering + conditional writes |
| Deployment | Sidecar in actor pod | Sidecar in mesh-api pod |
