# RFC: Expose Flows to Gateway

**Status**: Draft (iterating)
**Date**: 2026-03-01
**Epic**: 1m01
**Supersedes**: Epic 1iqd (Design workflow for asya flows — yeeted)
**Related**: 1c0d (A2A protocol compliance), 1ixy (pause-resume), 1l01 (ABI protocol), 1mx1 (meshage rename)

---

## Table of Contents

- [1. Abstract](#1-abstract)
- [2. Motivation](#2-motivation)
- [3. Terminology](#3-terminology)
- [4. Conceptual Mapping: Asya to A2A](#4-conceptual-mapping-asya-to-a2a)
- [5. Dual-Channel A2A Message Pattern](#5-dual-channel-a2a-message-pattern)
- [6. Tool/Skill Registry](#6-toolskill-registry)
- [7. Route Simplification (CPS)](#7-route-simplification-cps)
- [8. Removing YAML Config Loading](#8-removing-yaml-config-loading)
- [9. CLI Integration](#9-cli-integration)
- [10. Data Residency: What Lives Where](#10-data-residency-what-lives-where)
- [11. Open Questions](#11-open-questions)
- [12. Future Work](#12-future-work)

---

## 1. Abstract

This RFC specifies how Asya flows (compiled actor pipelines) and standalone
actors are exposed as MCP tools and A2A skills through the gateway. It replaces
YAML-based static tool configuration with a DB-backed registry, aligns Asya's
data model with the A2A protocol, and introduces the "meshage" terminology to
resolve naming collisions.

The core insight is that flow metadata (entrypoint, input schema, description)
is business logic, not Kubernetes infrastructure. It belongs in the gateway's
persistent store, not in K8s labels, ConfigMaps, or CRDs. See ADR
`1iqd/adr-async-flow-crd-vs-labels.md` for the decision to use labels over
CRDs for flow grouping — this RFC builds on that decision by moving the
*exposure* concern (what's visible to clients) into the gateway.

---

## 2. Motivation

**Current state**: Tool definitions are static YAML files in a ConfigMap
(`routes.yaml`), loaded once at gateway startup. There is no dynamic
registration, no integration with the flow compiler, and no CLI command to
expose a flow or actor.

**Problems**:

1. **No dynamic registration** — adding/removing tools requires a ConfigMap
   update + gateway restart (or unimplemented fsnotify hot-reload).
2. **Route lists leak topology** — the gateway builds the full route
   (`[actor1, actor2, actor3]`) into the meshage. With flows, the routing is
   baked into routers via CPS — the gateway only needs the entrypoint.
3. **Naming collision** — Asya's "message" (the envelope in the actor mesh)
   collides with A2A's "Message" (an immutable conversation turn).
4. **No CLI integration** — no `asya flow expose` or `asya expose` commands.
5. **YAML -> DB** — flow metadata should persist in the gateway's PostgreSQL,
   not in a ConfigMap that's coupled to Helm chart deployments.

**Target state**: Flows and standalone actors are registered via a REST API
(`POST /tools/expose`), persisted in PostgreSQL, and dynamically available as
MCP tools and A2A skills without gateway restart.

---

## 3. Terminology

| Term | Definition |
|------|-----------|
| **Meshage** | The self-contained envelope traveling through the actor mesh. Contains id, route, payload, status, headers. Lives in queues (in-transit) or S3 (when paused). Formerly called "message" or "envelope." See epic 1mx1 for the rename. |
| **Task** | Gateway's metadata record tracking a meshage's lifecycle. Lives in PostgreSQL. Contains status, progress, pause_metadata, context_id. **No payload data.** |
| **Message** (A2A) | An immutable communication turn. Has role (user/agent), parts, contextId. Lives in the meshage payload (`history` field) for canonical turns, or streamed via FLY for ephemeral turns. **Not stored in gateway DB.** |
| **Tool** (MCP) | A named capability exposed via MCP `tools/list`. Has name, description, parameters. Maps to a single entrypoint actor. |
| **Skill** (A2A) | A named capability in the A2A Agent Card. Same backing data as a Tool, plus A2A-specific metadata (tags, input_modes, output_modes). |

---

## 4. Conceptual Mapping: Asya to A2A

| A2A Concept | Asya Mapping | Notes |
|-------------|-------------|-------|
| **Context** (`contextId`) | **Meshage** | The meshage IS the conversation container. Its identity = the context. Multi-turn conversations are pause-resume cycles on the same meshage. |
| **Task** | **Gateway Task record** | Metadata-only tracker in PostgreSQL (status, progress, pause_metadata). No payload data. |
| **Message** (streaming) | **FLY event** | Ephemeral upstream delivery via ABI `yield "FLY", {...}`. For tokens, thoughts, live status updates. Not persisted. |
| **Message** (history) | **Meshage `history` field** | Canonical turns appended to `payload.history` by actors. Persists through the mesh, survives pause-resume via S3. |
| **Artifact** | **Meshage result via x-sink** | Final output persisted to S3 by x-sink. |
| **Skill** | **Exposed actor/flow** | Registered in gateway DB `tools` table. Maps to entrypoint actor. |

### Key insight: A2A multi-turn = pause-resume

A2A's multi-turn conversation pattern maps directly to Asya's pause-resume
mechanism (RFC 1ixy):

1. User sends A2A message -> gateway creates task, dispatches meshage to mesh
2. Actor reaches x-pause -> meshage persisted to S3, task = `paused` / A2A `input_required`
3. User sends another A2A message with same contextId/taskId -> gateway dispatches to x-resume
4. x-resume loads persisted meshage, merges user input, continues pipeline
5. Repeat until terminal state

Each "conversation turn" is a pause-resume cycle. The conversation state lives
in the meshage (payload + history), NOT in the gateway DB.

---

## 5. Dual-Channel A2A Message Pattern

A2A Messages are modeled via two complementary channels depending on whether
they are transient signals or canonical records.

### 5.1 FLY Channel (Ephemeral Streaming)

For partial updates, token streaming, intermediate thoughts, live status:

```python
async def agent_actor(payload):
    async for token in model.stream(payload["query"]):
        yield "FLY", {"type": "status_update",
                       "message": {"role": "agent",
                                   "parts": [{"text": token}]}}
    payload["response"] = await model.complete(payload["query"])
    yield payload  # EMIT downstream
```

- Actor yields `"FLY", {...}` per ABI protocol (1l01)
- Runtime delivers to sidecar as upstream event
- Sidecar forwards to gateway (any upstream event, not only SSE)
- Gateway broadcasts to connected clients
- **Not persisted** — ephemeral transport only

**A2A semantic**: `StreamResponse.message` events.

### 5.2 Meshage History (Persistent)

For finalized turns, input requests, canonical responses:

```python
async def agent_actor(payload):
    result = await do_work(payload)

    # Append canonical turn to history
    payload.setdefault("history", [])
    payload["history"].append({
        "role": "agent",
        "parts": [{"text": "Analysis complete"}, {"data": result}]
    })

    payload["result"] = result
    yield payload  # EMIT downstream with history
```

- History travels with the meshage through the actor mesh
- Downstream actors can read prior turns from `payload["history"]`
- On x-pause, full meshage (including history) persisted to S3
- On resume, history is restored with the meshage

**A2A semantic**: `Task.history` (list of Messages).

### 5.3 Comparison

| Feature | FLY (Ephemeral) | Meshage History (Persistent) |
|---------|-----------------|------------------------------|
| **A2A semantic** | `StreamResponse.message` | `Task.history` |
| **Asya mechanism** | `yield "FLY", {...}` -> sidecar -> gateway | Appended to `payload["history"]` -> MQ |
| **Persistence** | None (real-time only) | Travels with meshage, survives pause-resume via S3 |
| **Primary use** | Streaming tokens, thoughts, live status | Multi-turn history, final answers, input prompts |
| **Visibility** | Connected clients only | Subsequent actors + late-joining clients |
| **Storage cost** | Zero | Grows per canonical turn (bounded by SQS 1MB limit) |

---

## 6. Tool/Skill Registry

### 6.1 Architecture: Thin DB Layer

Replace YAML config with a PostgreSQL `tools` table and REST API.

```
CLI / asya flow expose
         |
         v
POST /tools/expose  -->  ToolStore.Upsert()  -->  Registry.Refresh()
                                                       |
                                        MCP tools/list reads from registry
                                        A2A agent-card reads from registry
```

Follows the existing `TaskStore` pattern: DB is source of truth, in-memory
registry is the fast read path (atomic pointer swap for thread safety).

### 6.2 Database Schema

```sql
CREATE TABLE tools (
    name             TEXT PRIMARY KEY,
    actor            TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    parameters       JSONB NOT NULL DEFAULT '{}',
    timeout_sec      INTEGER,
    progress         BOOLEAN NOT NULL DEFAULT false,
    mcp_enabled      BOOLEAN NOT NULL DEFAULT true,
    a2a_enabled      BOOLEAN NOT NULL DEFAULT false,
    a2a_tags         TEXT[] NOT NULL DEFAULT '{}',
    a2a_input_modes  TEXT[] NOT NULL DEFAULT '{application/json}',
    a2a_output_modes TEXT[] NOT NULL DEFAULT '{application/json}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

| Column | Notes |
|--------|-------|
| `name` | Natural PK. Tool identifier across MCP, A2A, CLI. |
| `actor` | Single entrypoint actor name. Gateway resolves to queue: `asya-{namespace}-{actor}`. |
| `parameters` | Full JSON Schema object. Passed through to MCP/A2A without interpretation. |
| `mcp_enabled` | Visible in MCP `tools/list`. Default true. |
| `a2a_enabled` | Visible in A2A Agent Card skills. Default false. |
| `a2a_tags` | A2A skill tags for discoverability. |
| `a2a_input_modes` | A2A skill input MIME types. |
| `a2a_output_modes` | A2A skill output MIME types. |

TODO: Audit full A2A AgentSkill protobuf schema and map all fields to columns.

### 6.3 Gateway API

**Register (upsert):**

```http
POST /tools/expose
Content-Type: application/json

{
  "name": "process_order",
  "actor": "start-order-processing",
  "description": "Submit an order for processing",
  "parameters": {
    "type": "object",
    "properties": {
      "order_id": {"type": "string"}
    },
    "required": ["order_id"]
  },
  "timeout": 300,
  "progress": true,
  "mcp": true,
  "a2a": {
    "enabled": true,
    "tags": ["orders", "processing"]
  }
}

Response: 201 Created (or 200 OK if updated)
```

**List:**

```http
GET /tools

Response: 200 OK
[{"name": "process_order", "actor": "start-order-processing", ...}]
```

**Remove:**

```http
DELETE /tools/{name}

Response: 204 No Content
```

TODO: Define full request/response JSON schemas, error codes, validation rules.

### 6.4 Protocol Views

Both protocols read from the same `tools` table with different filters:

- MCP `tools/list`: `WHERE mcp_enabled = true`
- A2A Agent Card skills: `WHERE a2a_enabled = true`

### 6.5 In-Memory Registry Refresh

After each mutation (POST/DELETE), gateway reloads full tool list from DB
into in-memory registry. Thread-safe via `atomic.Value` (Go). In-flight
requests complete with old registry, new requests use updated one.

---

## 7. Route Simplification (CPS)

### Before: Gateway builds full route

```yaml
# routes.yaml (YAML config)
tools:
  - name: process_order
    route: [validator, processor, notifier]
```

Gateway creates meshage:
```json
{"route": {"prev": [], "curr": "validator", "next": ["processor", "notifier"]}}
```

### After: Gateway sends to entrypoint only

```sql
INSERT INTO tools (name, actor) VALUES ('process_order', 'start-order-processing');
```

Gateway creates meshage:
```json
{"route": {"prev": [], "curr": "start-order-processing", "next": []}}
```

The `start-order-processing` router writes the actual continuation via ABI:

```python
yield "SET", ".route.next", ["validator", "processor", "notifier"]
yield payload
```

In CPS, the continuation is decided at each step, not planned upfront.
The gateway only needs the entrypoint. This applies identically to standalone
actors — a single actor with empty `next` is just an entrypoint.

**Removed from gateway**: `routes` map (named route templates), `RouteSpec`
(actors list vs template reference). A tool maps to exactly one actor.

---

## 8. Removing YAML Config Loading

The YAML-based tool config is fully replaced by the DB-backed registry.

**Removed:**
- `config.LoadConfig()` from `main.go`
- `ASYA_CONFIG_PATH` env var
- `routes-configmap.yaml` from Helm chart
- `config/routes.go` route template resolution

**Added:**
- Sqitch migration creating `tools` table
- `ToolStore` interface in `internal/toolstore/`
- `/tools/expose`, `/tools`, `/tools/{name}` endpoints

**Migration path for existing YAML deployments:**

1. **CLI migration script** (recommended):
   `asya tools migrate --from routes.yaml --gateway-url http://...`
   Reads YAML, POSTs each tool to the gateway API. Explicit, auditable,
   GitOps-friendly.

2. **Gateway seed flag** (alternative):
   `ASYA_SEED_CONFIG_PATH` — if set and `tools` table is empty, load from
   YAML on first boot. One-time seed, not ongoing.

---

## 9. CLI Integration

```bash
# Expose a compiled flow
asya flow expose my_flow.py \
  --gateway-url http://localhost:8080 \
  --name process_order \
  --description "Submit an order"

# Expose a standalone actor
asya expose my-actor \
  --gateway-url http://localhost:8080 \
  --name my_tool \
  --description "Do something"

# List exposed tools
asya tools list --gateway-url http://localhost:8080

# Remove
asya tools remove process_order --gateway-url http://localhost:8080
```

**Gateway access**: `--gateway-url` flag or `ASYA_GATEWAY_URL` env var.

**Flow metadata extraction** (`asya flow expose`):

| Metadata | Source | Status |
|----------|--------|--------|
| name | Flow function name (or `--name`) | Available |
| actor | `start_{flow_name}` (compiler convention) | Available |
| description | Flow function docstring | Requires parser enhancement |
| parameters | Type hints / annotations | Future |

---

## 10. Data Residency: What Lives Where

```
PostgreSQL (gateway)         S3/MinIO (state proxy)       Queues (SQS/RMQ)
--------------------         ---------------------        ----------------
Tool/skill registry:         Paused meshages:             Meshages in transit:
 - name, actor                - full payload               - id, route, payload
 - description                - full route                 - status, headers
 - parameters (schema)        - headers                    - history (canonical)
 - mcp/a2a flags              - history (canonical)
 - timeout, progress                                       (ephemeral, acked
                              x-sink results:               after processing)
Task metadata:                - final payload -> S3
 - id, status
 - progress %
 - pause_metadata
 - context_id
 - created/updated

NO payload data!              ALL payload data!
```

---

## 11. Open Questions

1. **`history` field schema**: Should the history array use A2A's Message
   format directly (`{role, parts}`) or define an Asya-native format?
   Using A2A format is simpler (no translation in gateway) but couples
   meshage internals to A2A. Need to dig into A2A Message/Part protobuf
   definition in detail.

2. **GetTask history retrieval**: History lives in the meshage (queues/S3),
   not gateway DB. For `GetTask` with `historyLength > 0`:
   (a) checkpoint actor persists meshage state, retrieval actor fetches on demand;
   (b) x-sink result includes final history;
   (c) defer — corner case for later.

3. **Full A2A AgentSkill schema audit**: Map every field in the A2A AgentSkill
   protobuf to the `tools` table. Current schema may be incomplete.

4. **REST API path structure**: `POST /tools/expose` coexists with
   `POST /tools/call`. Needs cleanup in a broader REST API redesign.

5. **Tool versioning**: If a flow is recompiled with a different parameter
   schema, is that an update or a new version?

6. **YAML migration path**: CLI script vs gateway seed flag.

---

## 12. Future Work

- **Parameter schema extraction**: Auto-detect input schema from flow.py
  function signatures, type hints, or decorator annotations.
- **Dynamic self-exposure**: Actor registers itself as a tool at startup.
- **A2A extended agent card**: Auth-gated agent details with richer metadata.
- **Tool health/readiness**: Track whether entrypoint actor is deployed and
  ready (K8s label integration or actor health checks).
- **Meshage rename rollout**: See epic 1mx1.
