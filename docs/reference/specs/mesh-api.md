---
description: "Mesh API spec: envelope CRUD, SSE streaming, sidecar event publishing, two-port architecture"
---

# Mesh API

The `asya-mesh-api` binary serves the `/api/v1/mesh/` HTTP API for envelope
lifecycle management. It replaces the legacy `mode=mesh` gateway deployment
with a dedicated microservice.

**Source**: `src/asya-gateway/cmd/mesh-api/`

## Architecture

Two-port HTTP server:

- **External port** (default 8080): client-facing CRUD + SSE
- **Internal port** (default 8081): sidecar event publishing + heartbeat

Persistence is delegated to a [pg-kv](../state-proxy-connectors/pg.md) sidecar
over Unix socket. The mesh-api binary never connects to PostgreSQL directly.

## Route Map

### External (port 8080)

| Method | Path | Auth | Caller | Description |
|--------|------|------|--------|-------------|
| `POST` | `{prefix}/mesh/` | Network isolation | Protocol adapters, sidecars | Create envelope |
| `GET` | `{prefix}/mesh/` | Network isolation | Protocol adapters, operators | List envelopes |
| `GET` | `{prefix}/mesh/{id}` | Network isolation | Protocol adapters, operators | Get envelope |
| `GET` | `{prefix}/mesh/{id}/events` | Network isolation | Protocol adapters, SSE clients | SSE event stream |
| `DELETE` | `{prefix}/mesh/{id}` | Network isolation | Protocol adapters | Cancel envelope |
| `GET` | `/health` | Public | K8s probes | Health check |

### Internal (port 8081)

| Method | Path | Auth | Caller | Description |
|--------|------|------|--------|-------------|
| `POST` | `{prefix}/mesh/{id}/events` | Network isolation | Sidecar | Publish status/FLY event |
| `GET` | `{prefix}/mesh/{id}` | Network isolation | Sidecar | Heartbeat check |
| `GET` | `/health` | Public | K8s probes | Health check |

Default prefix: `/api/v1` (configurable via `ASYA_MESH_API_PREFIX`).

---

## External API

### `POST {prefix}/mesh/?actor={name}`

Create an envelope and dispatch to the actor's queue.

**Query parameters:**

| Param | Required | Description |
|-------|----------|-------------|
| `actor` | Yes | Target actor queue name |
| `namespace` | No | Namespace override (defaults to `ASYA_NAMESPACE`) |

**Request** `application/json`:

```json
{
  "payload": { "query": "Hello" },
  "headers": { "trace_id": "abc" },
  "timeout": 300
}
```

All fields are optional. `timeout` is in seconds; when set, a `deadline_at`
timestamp is computed and stored.

**Response** `201 application/json`:

```json
{ "id": "550e8400-e29b-41d4-a716-446655440000" }
```

The envelope is stamped with `x-asya-gateway-url` in headers before dispatch.

---

### `GET {prefix}/mesh/`

List envelopes with optional filtering and pagination.

**Query parameters:**

| Param | Default | Description |
|-------|---------|-------------|
| `status` | _(all)_ | Filter by status (`pending`, `running`, `succeeded`, `failed`, `canceled`) |
| `limit` | _(none)_ | Max results |
| `offset` | `0` | Pagination offset |

**Response** `200 application/json`:

```json
{
  "messages": [
    {
      "id": "...",
      "status": "running",
      "created_at": "2026-04-17T...",
      "updated_at": "2026-04-17T...",
      "data": { ... }
    }
  ],
  "total": 42
}
```

Default sort: `-created_at` (newest first).

---

### `GET {prefix}/mesh/{id}`

Get a single envelope.

**Response** `200 application/json`: same shape as list items.

**Errors**: `404` if not found.

---

### `GET {prefix}/mesh/{id}/events`

SSE stream of envelope lifecycle events.

**Headers**: `Content-Type: text/event-stream`, `Cache-Control: no-cache`

**Behavior**:

1. Returns current status as first event (catch-up)
2. If already terminal, sends one event and closes
3. Otherwise, streams live events until terminal or client disconnect
4. Sends `:keepalive` comment every 15 seconds

**SSE format**:

```
event: status
data: {"status":"running","actor":"train-model","progress":50.0}

event: fly
data: {"text":"token..."}

event: status
data: {"status":"succeeded"}

```

---

### `DELETE {prefix}/mesh/{id}`

Cancel an envelope. Idempotent — returns 204 even if already terminal.

**Response**: `204 No Content`

**Errors**: `404` if not found.

---

## Internal API

### `POST {prefix}/mesh/{id}/events`

Publish a lifecycle event from a sidecar. This single endpoint replaces the
legacy gateway's separate `/mesh/{id}/progress`, `/mesh/{id}/final`, and
`/mesh/{id}/fly` endpoints.

**Request** `application/json` — status event:

```json
{
  "type": "status",
  "status": "running",
  "data": { "actor": "train-model", "progress": 50 }
}
```

**Request** `application/json` — FLY event:

```json
{
  "type": "fly",
  "data": { "text": "streaming token..." }
}
```

**Response**: `204 No Content`

**Behavior**:

- Status events update the store with monotonic ordering enforcement.
  A stale update (e.g. `running` after `succeeded`) is silently ignored (204).
- FLY events are ephemeral — published to SSE subscribers but never written
  to the store.

**Errors**: `404` if envelope not found. `400` for invalid JSON.

---

### `GET {prefix}/mesh/{id}`

Same as external GET. Used by sidecars for heartbeat/liveness checks.

---

## Status Model

Monotonic ordering — once a status is set, only higher-order statuses can
overwrite it:

```
pending (0) → running (1) → paused (2) → succeeded|failed|canceled (3)
```

Terminal states (`succeeded`, `failed`, `canceled`) have equal order and
cannot overwrite each other.

---

## Breaking Changes from Legacy Gateway Mesh Routes

This API replaces the `mode=mesh` deployment of `asya-gateway`. The old
routes are deprecated. See [gateway-api.md](gateway-api.md) § Mesh Routes.

| Old Route | New Route | Notes |
|-----------|-----------|-------|
| `POST /mesh` | `POST {prefix}/mesh/` | Path changed; request body differs |
| `GET /mesh/{id}` | `GET {prefix}/mesh/{id}` | Compatible (response shape differs) |
| `GET /mesh/{id}/stream` | `GET {prefix}/mesh/{id}/events` | Renamed; SSE format changed |
| `GET /mesh/{id}/active` | _(removed)_ | Use GET to check status instead |
| `POST /mesh/{id}/progress` | `POST {prefix}/mesh/{id}/events` | Unified into events POST with `type: "status"` |
| `POST /mesh/{id}/final` | `POST {prefix}/mesh/{id}/events` | Unified into events POST with terminal status |
| `POST /mesh/{id}/fly` | `POST {prefix}/mesh/{id}/events` | Unified into events POST with `type: "fly"` |
| `POST /mesh/config-reload` | _(removed)_ | Config is static in mesh-api |

**New endpoints** (no legacy equivalent):

| Route | Description |
|-------|-------------|
| `GET {prefix}/mesh/` | List envelopes with filtering/pagination |
| `DELETE {prefix}/mesh/{id}` | Cancel an envelope |

### Migration

To restore backward-compatible routes, set `ASYA_MESH_API_PREFIX=""` which
produces `/mesh/` paths. The SSE endpoint is still renamed (`/events` not
`/stream`) and the unified events POST replaces the three separate endpoints.
