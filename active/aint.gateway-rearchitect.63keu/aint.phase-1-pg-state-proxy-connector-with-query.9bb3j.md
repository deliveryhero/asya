---
title: "Phase 1: PG state-proxy connector with /query"
status: open
priority: 1 # high
---

Go PostgreSQL state-proxy connector implementing StateProxyConnector interface. KV ops (read/write/list/delete) + /query endpoint with Mango-style filter DSL. Self-configuring expression indexes from env vars. Schema: single kv table (key TEXT PK, value JSONB, created_at, updated_at). ~400-500 LOC Go.

Implementation:
- New package: src/asya-gateway/internal/stateproxy/pg/
- KV: read=SELECT, write=UPSERT, list=LIKE, delete=DELETE
- /query: filter-to-SQL translator with operators (,,,,,,,,,)
- Parameterized SQL (no injection), input validation
- On startup: CREATE TABLE IF NOT EXISTS, CREATE INDEX CONCURRENTLY from STATE_PROXY_PG_INDEXES env var
- GIN index on value for ad-hoc queries
- HTTP server on Unix socket (same pattern as existing Python connectors)
- pgx driver for PG connection

Testing:
- Unit: filter-to-SQL translator, operator parsing
- Component: Docker Compose with PG, test all KV ops + query
- E2E: use in Kind cluster tests

Depends on: nothing (can start immediately)
