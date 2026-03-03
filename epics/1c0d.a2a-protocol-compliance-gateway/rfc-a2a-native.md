# RFC: Native A2A Protocol Support for Asya Gateway

**Status**: Draft
**Date**: 2026-03-02
**Epic**: 1c0d (A2A Protocol Compliance for Gateway)
**Supersedes**: `epic.md` (original A2A RFC) and `rfc.md` (expose flows) — **this is the single source of truth**
**Related**: 1mx1 (envelope rename), 1ixy (pause-resume), 1l01 (ABI protocol), 1dmf (stateful actors)

---

## Table of Contents

- [1. Abstract](#1-abstract)
- [2. Motivation](#2-motivation)
- [3. Terminology](#3-terminology)
- [4. Conceptual Mapping: Asya to A2A](#4-conceptual-mapping-asya-to-a2a)
- [5. Data Model](#5-data-model)
  - [5.0 A2A Schemas and Storage Mapping](#50-a2a-schemas-and-storage-mapping)
  - [5.1 Task State Machine](#51-task-state-machine)
  - [5.2 Message-to-Envelope Translation](#52-message-to-envelope-translation)
  - [5.3 Artifact Model](#53-artifact-model)
  - [5.4 History in Envelope Payload](#54-history-in-envelope-payload)
  - [5.5 Context as Grouping Attribute](#55-context-as-grouping-attribute)
  - [5.6 ID Scheme](#56-id-scheme)
  - [5.7 Dual-Channel Message Pattern](#57-dual-channel-message-pattern)
- [6. Gateway Architecture](#6-gateway-architecture)
  - [6.1 Endpoint Layout](#61-endpoint-layout)
  - [6.2 a2a-go Library Integration](#62-a2a-go-library-integration)
  - [6.3 AgentExecutor Implementation](#63-agentexecutor-implementation)
  - [6.4 TaskStore Adapter](#64-taskstore-adapter)
- [7. A2A Service Methods](#7-a2a-service-methods)
  - [7.1 SendMessage](#71-sendmessage)
  - [7.2 SendStreamingMessage](#72-sendstreamingmessage)
  - [7.3 GetTask](#73-gettask)
  - [7.4 ListTasks](#74-listtasks)
  - [7.5 CancelTask](#75-canceltask)
  - [7.6 SubscribeToTask](#76-subscribetotask)
  - [7.7 Push Notification CRUD](#77-push-notification-crud)
  - [7.8 GetExtendedAgentCard](#78-getextendedagentcard)
- [8. Agent Card and Skill Discovery](#8-agent-card-and-skill-discovery)
  - [8.1 Agent Card Structure](#81-agent-card-structure)
  - [8.2 Skill Registration](#82-skill-registration)
  - [8.3 Skill Resolution Strategy](#83-skill-resolution-strategy)
  - [8.4 Registration API](#84-registration-api)
- [9. Streaming Architecture](#9-streaming-architecture)
  - [9.1 FLY to A2A StreamResponse Mapping](#91-fly-to-a2a-streamresponse-mapping)
  - [9.2 SSE Event Format](#92-sse-event-format)
  - [9.3 Actor-to-Client Streaming Flow](#93-actor-to-client-streaming-flow)
  - [9.4 Blocking Mode](#94-blocking-mode)
  - [9.5 Multi-Frame Streaming Pipeline](#95-multi-frame-streaming-pipeline)
- [10. Pause/Resume and input_required](#10-pauseresume-and-input_required)
  - [10.1 Actor-Initiated Pause](#101-actor-initiated-pause)
  - [10.2 Gateway State Transition](#102-gateway-state-transition)
  - [10.3 User-Initiated Resume](#103-user-initiated-resume)
  - [10.4 History Accumulation During Pause/Resume](#104-history-accumulation-during-pauseresume)
- [11. Internal Routes: Mesh Layer](#11-internal-routes-mesh-layer)
  - [11.1 Renamed Sidecar-Facing Routes](#111-renamed-sidecar-facing-routes)
  - [11.2 Sidecar Changes for A2A](#112-sidecar-changes-for-a2a)
- [12. Authentication and Security](#12-authentication-and-security)
- [13. Database Schema](#13-database-schema)
- [14. Implementation Phases](#14-implementation-phases)
- [15. Testing Strategy](#15-testing-strategy)
- [16. Future Work](#16-future-work)

---

## 1. Abstract

This RFC specifies how asya-gateway implements native A2A (Agent-to-Agent) protocol
support using the official `a2a-go` library (`github.com/a2aproject/a2a-go`). It
covers the full A2A specification: all 11 service methods, Agent Card discovery,
streaming via SSE, task lifecycle management, pause/resume mapping to
`input_required`, authentication, and push notifications.

The design principle is **A2A as a facade over the actor mesh**. The gateway
implements the `a2a-go` `AgentExecutor` interface to translate A2A operations into
envelope dispatch, and the `TaskStore` interface to wrap the existing PostgreSQL
store. The `a2a-go` library handles JSON-RPC dispatch, SSE formatting, request
validation, and protocol compliance. Asya's internal architecture (envelopes,
sidecars, actors, queues) remains unchanged.

All gateway routes are organized into three fixed namespaces (`/a2a`, `/mcp`,
`/mesh`) under a configurable base prefix `ASYA_BASE_PREFIX` (default: empty).
Exception: `/.well-known/agent.json` is always at root per A2A spec.

---

## 2. Motivation

**Current state**: asya-gateway has partial A2A support with hand-rolled types, a
custom JSON-RPC dispatcher, and incomplete method coverage. The implementation
diverges from the spec in field names, streaming format, and error handling.

**Problems**:

1. **Incomplete spec coverage**: Only 3 of 11 methods implemented
   (`message/send`, `message/stream`, `tasks/get`).
2. **Hand-rolled types**: Go structs in `internal/a2a/types.go` may drift from the
   normative protobuf schema as the spec evolves.
3. **No official library**: The `a2a-go` library provides generated types, server
   framework, JSON-RPC dispatch, and SSE helpers — all currently reimplemented.
4. **History model undefined**: No design for A2A conversation history.
5. **Skill resolution untested**: No mechanism for dynamic skill-based routing.
6. **Auth missing**: No authentication on A2A endpoints.

**Target state**: Full A2A protocol compliance using the official `a2a-go` library.
External agents can discover Asya, send messages, stream results, track tasks,
manage push notifications, and participate in multi-turn conversations with
pause/resume — all through standard A2A operations.

---

## 3. Terminology

| Term | Definition |
|------|-----------|
| **Envelope** | Asya's internal envelope traveling through the actor mesh. Contains `id`, `route`, `payload`, `status`, `headers`. Lives in queues (in-transit) or S3 (paused). Formerly "message" or "envelope" (see epic 1mx1). |
| **Task** (A2A) | Assembled from two sources: metadata from gateway DB (id, context_id, status) + data from `payload.a2a.task` (history, artifacts, metadata). See Section 5.0. |
| **Context** (`context_id`) | A grouping attribute on tasks. Groups related tasks in a conversation/session. Just a TEXT column — not a first-class entity. Server-generated UUID if not provided by client. |
| **Message** (A2A) | Proto `Message`: immutable communication turn with `role`, `parts`, `message_id`. Stored at `payload.a2a.task.history[]`. |
| **Artifact** (A2A) | Proto `Artifact`: task output with `artifact_id`, `name`, `parts`. Stored at `payload.a2a.task.artifacts[]`. Content in external storage. |
| **Skill** (A2A) | A named capability in the Agent Card. Maps to an exposed actor/flow in the `tools` table. |
| **Tool** (MCP) | A named capability in MCP `tools/list`. Same backing data as a Skill. |
| **FLY** | ABI yield verb for upstream streaming: `yield "FLY", {...}`. Delivers events from actor → runtime → sidecar → gateway → SSE client. |

---

## 4. Conceptual Mapping: Asya to A2A

### 4.1 Entity Mapping

| A2A Concept | Asya Mapping | Notes |
|-------------|-------------|-------|
| **Context** (`contextId`) | TEXT column on tasks table | Grouping key for conversations. One context can have many tasks. Server-generated UUID if not provided. |
| **Task** | Assembled: DB metadata (id, status, context_id) + `payload.a2a.task` (history, artifacts, metadata) | See Section 5.0 for split. 1:1 with a envelope lifecycle. |
| **Message** (client → server) | Creates envelope or resumes paused task | User input dispatched to the actor mesh. |
| **Message** (server → client, streaming) | FLY event in A2A StreamResponse format | Ephemeral upstream delivery via ABI. Not persisted. |
| **Message** (server → client, history) | `payload.a2a.task.history[]` | Canonical turns, survive pause/resume via S3. |
| **Artifact** | `payload.a2a.task.artifacts[]`, Part content in external storage | Gateway stores only metadata pointers, never content. |
| **Skill** | Exposed actor/flow in `tools` table | `WHERE a2a_enabled = true`. Maps to entrypoint actor. |
| **AgentCard** | Generated dynamically from `tools` table | Cached in memory, regenerated on tool registry change. |

For metadata - gateway's DB (PostgreSQL) is source of truth. However, it can't store data (messages, artifacts) - these are stored either in envelope payloads or on external storages (using asya's state proxy functionality).

### 4.2 Lifecycle Mapping

A2A Task lifecycle maps to envelope lifecycle:

```
Client                    Gateway                     Actor Mesh
  |                         |                            |
  |-- SendMessage --------->|                            |
  |                         |   Create Task (DB)         |
  |                         |   Create Envelope           |
  |                         |-- Dispatch to queue ------>|
  |<-- Task{submitted} -----|                            |
  |                         |                            |
  |                         |<-- /mesh/{id}/progress ----|  (sidecar reports)
  |<-- StatusUpdate{working}|                            |
  |                         |                            |
  |                         |<-- FLY events -------------|  (actor streams)
  |<-- ArtifactUpdate ------|                            |
  |                         |                            |
  |                         |<-- /mesh/{id}/final -------|  (x-sink reports)
  |<-- StatusUpdate{done} --|                            |
```

### 4.3 Why Task:Envelope is 1:1

Each A2A Task corresponds to exactly one envelope lifecycle. When a envelope is
paused and later resumed:

- The envelope ID stays the same (x-resume loads the original envelope from S3)
- The task ID stays the same
- A NEW resume envelope is created and sent to x-resume, but x-resume merges it
  into the original envelope, continuing with the original ID

Multiple tasks in the same context are independent envelopes with different IDs,
sharing only the `context_id` attribute.

---

## 5. Data Model

### 5.0 A2A Schemas and Storage Mapping

The A2A `Task` proto has these fields (from `a2a.proto`):

```protobuf
message Task {
  string id = 1;                    // REQUIRED
  string context_id = 2;            // REQUIRED
  TaskStatus status = 3;            // REQUIRED
  repeated Artifact artifacts = 4;  // optional
  repeated Message history = 5;     // optional
  Struct metadata = 6;              // optional
}
```

In Asya, the A2A Task is **split across two storage layers**:

```
A2A Task field     Storage location                        Why
────────────────── ─────────────────────────────────────── ──────────────────────────────
id                 Gateway DB (tasks.id)                   Metadata — always available
                   + payload.a2a.task.id (duplicate)       Travels with envelope for self-containment
                   + headers.x-asya-a2a-task-id (dup)      Sidecar access without payload parsing
context_id         Gateway DB (tasks.context_id)           Metadata — indexed for queries
                   + payload.a2a.task.context_id (dup)     Travels with envelope
                   + headers.x-asya-a2a-context-id (dup)   Sidecar access
status             Gateway DB (tasks.status)               Metadata — mutable, query filter
                   NOT in payload (would be stale)
artifacts          payload.a2a.task.artifacts              DATA — can be large (files, blobs)
history            payload.a2a.task.history                DATA — grows with conversation
metadata           payload.a2a.task.metadata               DATA — A2A Task.metadata
```

**`payload.a2a.task` structure**: Mirrors the A2A `Task` proto exactly. The
payload contains a namespace `a2a` with a `task` object whose fields use A2A's
canonical schemas — no Asya-specific wrappers or field renames:

```json
{
  "a2a": {
    "task": {
      "id": "task-uuid",
      "context_id": "ctx-uuid",
      "status": {
        "state": "working",
        "timestamp": "2026-03-02T10:00:00Z"
      },
      "history": [ ...A2A Message objects... ],
      "artifacts": [ ...A2A Artifact objects... ],
      "metadata": {
        "skill": "analyze-doc"
      }
    }
  },
  "query": "actor-facing fields at root",
  "depth": 3
}
```

**Why mirror the proto**: The structure inside `payload.a2a.task` uses the
exact field names and types from the A2A `Task` proto. This means:
- No translation needed when reading/writing A2A data in actors
- `a2a-go` types can be serialized/deserialized directly into this location
- All required fields are present, including `status`

**`status` in payload is a snapshot**: `payload.a2a.task.status` is REQUIRED
by the A2A proto (`TaskStatus status = 3 [REQUIRED]`), so it MUST be present.
The gateway sets it at dispatch time and actors MAY update it as the envelope
flows. However, it is a **point-in-time snapshot** — the gateway DB is the
authoritative source. The sidecar uses `GET /mesh/{id}/active` to check the
gateway's authoritative status before processing:

| Location | What it stores | Authoritative? |
|----------|---------------|----------------|
| Gateway DB (`tasks.status`) | Current task state | **Yes** — single source of truth |
| `payload.a2a.task.status` | Snapshot at dispatch/last-update time | **No** — may be stale |
| `GET /mesh/{id}/active` | Gateway's live answer | **Yes** — real-time check |

**Why duplicate in headers**: The sidecar needs `task_id` for progress
reporting (`POST /mesh/{id}/progress`) but must NOT parse payload contents.
Headers provide lightweight access. `envelope.id` happens to equal `task_id`
today, but this is a convenience, not a hard contract — the sidecar should
read from headers.

**Gateway Task reconstruction**: When the gateway needs to return a full A2A
`Task` (for GetTask, SendMessage response, etc.), it assembles it from both
sources:

```
A2A Task response = {
  id:         ← tasks.id                         (DB, authoritative)
  context_id: ← tasks.context_id                 (DB, authoritative)
  status:     ← tasks.status → toA2AState()      (DB, authoritative, NOT from payload)
  artifacts:  ← payload.a2a.task.artifacts        (S3, optional fetch)
  history:    ← payload.a2a.task.history          (S3, optional fetch)
  metadata:   ← payload.a2a.task.metadata         (S3, optional fetch)
}
```

**Critical**: `status` in the response ALWAYS comes from the gateway DB, never
from `payload.a2a.task.status`. The payload snapshot may be stale (e.g., payload
says WORKING but user already cancelled → DB says CANCELED).

For in-flight tasks where the envelope is in a queue (not accessible), the
gateway omits `artifacts`, `history`, and `metadata` — all optional per spec.

The following subsections reference A2A proto types. For the full type mapping
to `a2a-go` Go types, see Appendix A.

### 5.1 Task State Machine

A2A defines 9 task states. Asya's internal states map as follows (note: `TaskStatus` to be renamed to `EnvelopeStatus`):

```
A2A TaskState              Asya TaskStatus       Category
─────────────────────────────────────────────────────────────
SUBMITTED                  pending               Active
WORKING                    running               Active
COMPLETED                  succeeded             Terminal
FAILED                     failed                Terminal
CANCELED                   canceled              Terminal
REJECTED                   rejected              Terminal
INPUT_REQUIRED             paused                Interrupted
AUTH_REQUIRED              auth_required         Interrupted (future)
UNKNOWN                    unknown               Error
```

**State transitions** (arrows show valid transitions):

```
                 ┌────────────────────────────────────┐
                 │                                    │
                 v                                    │
  ┌──────────┐     ┌──────────┐     ┌───────────┐     │
  │SUBMITTED │────>│ WORKING  │────>│ COMPLETED │     │
  └──────────┘     └──────────┘     └───────────┘     │
       │               │                              │
       │               ├──────────> FAILED            │
       │               │                              │
       │               ├──────────> CANCELED          │
       │               │                              │
       │               └──────────> INPUT_REQUIRED ───┘
       │                                 │              (resume)
       └──────────────────────────> REJECTED
```

**Translation functions** (in gateway):

```go
// Asya internal → A2A (outbound)
func toA2AState(s types.TaskStatus) a2a.TaskState {
    switch s {
    case "pending":        return a2a.TaskStateSubmitted
    case "running":        return a2a.TaskStateWorking
    case "succeeded":      return a2a.TaskStateCompleted
    case "failed":         return a2a.TaskStateFailed
    case "canceled":       return a2a.TaskStateCanceled
    case "rejected":       return a2a.TaskStateRejected
    case "paused":         return a2a.TaskStateInputRequired
    case "auth_required":  return a2a.TaskStateAuthRequired
    default:               return a2a.TaskStateUnknown
    }
}

// A2A → Asya internal (inbound, for filters)
func fromA2AState(s a2a.TaskState) types.TaskStatus {
    // reverse mapping
}
```

### 5.2 Message-to-Envelope Translation

When the gateway receives an A2A `SendMessageRequest`, it translates the A2A
`Message` into a envelope `payload` and stamps A2A metadata in envelope `headers`.

**Design principle**: The envelope payload contains TWO distinct areas:
- `payload.a2a.task` — A2A Task object (history, artifacts, metadata). Mirrors
  the A2A `Task` proto exactly. Managed by the gateway and crew actors.
- Everything else — Actor-custom fields. Managed by the actor handler's business
  logic. The gateway extracts user intent from Message parts and places it at
  the payload root for actor consumption.

**Inbound translation** (A2A Message → envelope):

```
A2A SendMessageRequest {              Envelope {
  message: {                            id: "envelope-uuid",
    message_id: "m-001",               route: {prev:[], curr:"analyzer", next:[...]},
    context_id: "c-001",               headers: {
    role: "user",                         "x-asya-a2a-task-id": "envelope-uuid",
    parts: [                              "x-asya-a2a-context-id": "c-001"
      {data: {                          },
        query: "Analyze this",          payload: {
        format: "pdf"                     "a2a": {
      }}                                    "task": {
    ]                                         "id": "envelope-uuid",
  }                                           "context_id": "c-001",
}                                             "history": [{
                                                "message_id": "m-001",
                                                "role": "user",
                                                "parts": [{"data": {
                                                  "query": "Analyze this",
                                                  "format": "pdf"}}]
                                              }],
                                              "metadata": {"skill": "analyze-doc"}
                                            }
                                          },
                                          "query": "Analyze this",
                                          "format": "pdf"
                                        }
                                      }
```

**Payload construction rules**:

1. **Always first**: Initialize `payload.a2a.task` with `id`, `context_id`,
   and append the full A2A Message to `payload.a2a.task.history[]`.

2. **Single data Part**: Unwrap `data.Value` and merge at payload root.
   This is the common case for structured API calls.
   ```json
   parts: [{data: {query: "...", depth: 3}}]
   → payload: {a2a: {task: {id:..., history:[...]}}, query: "...", depth: 3}
   ```

3. **Text-only Part(s)**: Concatenate text parts with `\n` and store as
   `payload.query` (conventional field name for text-based skills).
   ```json
   parts: [{text: "Analyze this"}]
   → payload: {a2a: {task: {id:..., history:[...]}}, query: "Analyze this"}
   ```

4. **Mixed or multi-part**: The full A2A Message with all parts is preserved
   in `payload.a2a.task.history`. Actor-facing extraction is best-effort — if
   there's a single data Part among the parts, merge it at root. Otherwise,
   actors read from `payload.a2a.task.history[-1].parts` directly.

**Inbound blob handling**: If a client sends a Message with `raw` (binary) Parts,
the gateway MUST externalize them before dispatching the envelope:
1. Write the `raw` content to external storage via state proxy
2. Replace the `raw` Part with a `url` Part referencing the stored content
3. This protects the pipeline from queue size limit violations

Small `text` and `data` Parts in Messages are stored inline in
`payload.a2a.task.history` (they're typically prompt-sized).

**No synthetic fields**: The gateway does NOT create `_a2a_files`, `_a2a_text`,
or any underscore-prefixed convenience fields. The canonical A2A data lives in
`payload.a2a.task` and actors that need multi-part awareness read from there.

**Outbound translation** (envelope result → A2A response): See Section 5.3.

### 5.3 Artifact Model

`payload.a2a.task.artifacts` stores `repeated Artifact` — the same schema as A2A
`Task.artifacts`:

```protobuf
message Artifact {
  string artifact_id = 1;         // REQUIRED — unique within task
  string name = 2;                // optional — human-readable
  string description = 3;         // optional
  repeated Part parts = 4;        // REQUIRED — content
  Struct metadata = 5;            // optional
  repeated string extensions = 6; // optional
}

message Part {
  oneof content {
    string text = 1;              // text content
    bytes raw = 2;                // binary (base64 in JSON)
    string url = 3;               // URL pointing to content
    Value data = 4;               // structured JSON
  }
  Struct metadata = 5;            // optional
  string filename = 6;            // optional (e.g. "report.pdf")
  string media_type = 7;          // MIME type (e.g. "application/json")
}
```

#### 5.3.1 URL-Only Artifact Constraint

**Blob content MUST NOT live in the envelope payload.** Envelopes travel through
message queues (SQS limit: 256KB, RabbitMQ practical limit: ~128MB but impacts
throughput). Inline `raw` or large `data`/`text` Parts would blow up the
payload, fail queue delivery, or degrade the entire pipeline.

**Rule**: Every Part inside `payload.a2a.task.artifacts` MUST use the `url`
content type. All actual content lives in external storage (S3/MinIO via state
proxy). The artifact in the payload is a **manifest of URLs**, not a container
of data:

```json
{
  "a2a": {
    "task": {
      "artifacts": [
        {
          "artifact_id": "analysis-result",
          "name": "Analysis Result",
          "parts": [
            {
              "url": "s3://bucket/results/analysis.json",
              "media_type": "application/json",
              "filename": "analysis.json"
            },
            {
              "url": "s3://bucket/reports/report.pdf",
              "media_type": "application/pdf",
              "filename": "report.pdf"
            }
          ]
        }
      ]
    }
  }
}
```

**What the proto allows vs. what Asya allows**:

| Part type | A2A proto | In `payload.a2a.task.artifacts` | In A2A GetTask response |
|-----------|-----------|--------------------------------|-------------------------|
| `url` | Yes | **Yes** — the only type allowed | Yes (passed through) |
| `text` | Yes | **No** — write to storage, use URL | Yes (materializer resolves) |
| `data` | Yes | **No** — write to storage, use URL | Yes (materializer resolves) |
| `raw` | Yes | **No** — write to storage, use URL | Yes (materializer resolves) |

#### 5.3.2 Getting Artifact URLs via xattr

The state proxy (RFC 1dmf) provides external URLs via the **xattr API** — actors
use `os.getxattr()` (Python stdlib) to query backend metadata. No custom imports,
no knowledge of storage configuration. See task `1dmfx1` for full implementation.

```python
import os

# 1. Write content to external storage (existing pattern)
with open("/state/artifacts/report.pdf", "wb") as f:
    f.write(pdf_content)

# 2. Get the canonical backend URL (zero API calls — string concat)
url = os.getxattr("/state/artifacts/report.pdf", "user.asya.url").decode()
# → "s3://my-bucket/prefix/artifacts/report.pdf"

# 3. Or get a presigned URL for unauthenticated client access
presigned = os.getxattr("/state/artifacts/report.pdf", "user.asya.presigned_url").decode()
# → "https://my-bucket.s3.amazonaws.com/prefix/...?X-Amz-Signature=..."
```

**Available xattr attributes** (per connector):

| Attribute | Returns | Cost |
|-----------|---------|------|
| `user.asya.url` | `s3://bucket/key` canonical URI | Zero (string concat) |
| `user.asya.presigned_url` | Time-limited HTTPS URL | Local crypto (no network) |
| `user.asya.etag` | Content hash | HEAD request |
| `user.asya.content_type` | MIME type | HEAD request |

**Which URL to use in artifacts**: Use `user.asya.presigned_url` when the A2A
client needs direct HTTPS access without S3 credentials. Use `user.asya.url`
when the client has storage access or when a materializer will resolve it.

#### 5.3.3 Actor-Produced Artifacts

Actors write all content to external storage, then reference it by URL in the
artifact manifest:

```python
import json, os

async def handler(payload):
    result = analyze(payload["query"])

    # Write ALL outputs to external storage via state proxy
    analysis_proxy = "/state/artifacts/analysis.json"
    with open(analysis_proxy, "w") as f:
        json.dump(result, f)

    # get artifact URL:
    try:
        result_url = os.getxattr(analysis_proxy, "user.asya.url").decode()
    except OSError:
        result_url = analysis_proxy  # fallback - return asya-internal path (or none)

    # save report:
    report_proxy = "/state/artifacts/report.pdf"
    with open(report_proxy, "wb") as f:
        f.write(generate_pdf(result))

    # get artifact URL:
    try:
        report_url = os.getxattr(report_proxy, "user.asya.url").decode()
    except OSError:
        report_url = report_proxy  # fallback

    # Artifact contains ONLY url Parts — no inline data
    payload.setdefault("a2a", {}).setdefault("task", {}).setdefault("artifacts", [])
    payload["a2a"]["task"]["artifacts"].append({
        "artifact_id": "analysis-result",
        "name": "Analysis Result",
        "parts": [
            {"url": result_url, "media_type": "application/json",
             "filename": "analysis.json"},
            {"url": report_url, "media_type": "application/pdf",
             "filename": "report.pdf"}
        ]
    })

    return payload
```

**Using A2A pydantic types directly**: Actors MAY use bare A2A pydantic models
(e.g. `Artifact(...)`, `Part(...)`, `Message(...)`) or dataclasses/TypedDicts
instead of hand-written dicts. The runtime's JSON serializer duck-types common
serialization protocols (`model_dump`, `asdict`, etc.) so any JSON-serializable
object works transparently in payloads, return values, and FLY events. See task
`1mx1x2x3` for implementation details.

#### 5.3.4 Gateway Artifact Handling

When x-sink reports the final result to the gateway:

1. Gateway reads `payload.a2a.task.artifacts` from the result
2. All Parts are `url` references — gateway stores the manifest as-is
3. `GetTask(includeArtifacts=true)` returns the URL-only artifacts

For GetTask on completed tasks, the gateway fetches the envelope result from S3
(same mechanism as history) and extracts `payload.a2a.task.artifacts`.

**Client responsibility**: A2A clients receive `url` Parts and fetch content
directly from external storage. This is standard A2A behavior — the spec
explicitly supports URL-referenced content.

#### 5.3.5 Artifact Materializer Crew Actor (Future)

Some A2A clients expect inline content (`text`, `data`, `raw` Parts) rather
than URL references. A **materializer crew actor** resolves URLs to inline
content at the end of the pipeline:

```yaml
route: [analyzer, materializer, x-sink]
```

The materializer:
1. Reads `payload.a2a.task.artifacts[].parts` with `url` references
2. Fetches content from each URL via state proxy
3. Replaces `url` Parts with the appropriate inline type:
   - `application/json` → `data` Part
   - `text/*` → `text` Part
   - Binary (images, PDFs) → `raw` Part (base64)
4. Emits the enriched payload to x-sink

**When to use**: Only when the A2A client cannot follow URLs (e.g., sandbox
environments with no external network access). Most A2A clients handle URLs
natively.

**Queue size consideration**: The materializer MUST be the last actor before
x-sink. After materialization, the payload may exceed queue size limits, so
x-sink should receive it via direct HTTP (not queue). This is a future design
concern — see Phase 3+.

#### 5.3.6 Workflow Examples

Three concrete scenarios illustrate how artifacts flow through the system.

##### Scenario 1: Many Small Images (Batch Processing)

An actor processes a document and produces multiple images — each as a separate
Part with its own URL. All images belong to one Artifact (the "page renders").

```python
import os

def render_pages(payload):
    doc = load_document(payload["document_url"])
    parts = []

    for i, page in enumerate(doc.pages):
        # Write each image to state proxy
        path = f"/state/artifacts/page_{i:03d}.png"
        with open(path, "wb") as f:
            f.write(page.render_png())

        # Get external URL (zero-cost string concat)
        url = os.getxattr(path, "user.asya.url").decode()
        parts.append({
            "url": url,
            "media_type": "image/png",
            "filename": f"page_{i:03d}.png"
        })

    # One artifact, many parts — each part is a separate image
    payload.setdefault("a2a", {}).setdefault("task", {}).setdefault("artifacts", [])
    payload["a2a"]["task"]["artifacts"].append({
        "artifact_id": "page-renders",
        "name": f"Rendered Pages ({len(parts)} images)",
        "parts": parts
    })
    return payload
```

**Resulting artifact in envelope payload**:
```json
{
  "artifact_id": "page-renders",
  "name": "Rendered Pages (12 images)",
  "parts": [
    {"url": "s3://bucket/artifacts/page_000.png", "media_type": "image/png", "filename": "page_000.png"},
    {"url": "s3://bucket/artifacts/page_001.png", "media_type": "image/png", "filename": "page_001.png"},
    "... (10 more)"
  ]
}
```

**Key point**: Each Part is ~100 bytes (URL + metadata). 1000 images = ~100KB of
URL manifests — well within SQS 256KB limit. The actual image data (potentially
GBs) stays in S3.

##### Scenario 2: Large File (Single Object Upload)

For large files (high-res images, videos, trained models), the actor writes a
single file. No chunking in the payload — the storage layer handles multipart
upload transparently.

```python
import os

async def generate_video(payload):
    # Generate or download a large video file
    video_data = await render_video(payload["scene_config"])

    # Write to state proxy — storage layer handles multipart upload
    # for files >5MB (S3 multipart upload is transparent to the actor)
    with open("/state/artifacts/output.mp4", "wb") as f:
        f.write(video_data)  # Could be 2GB — state proxy streams to S3

    url = os.getxattr("/state/artifacts/output.mp4", "user.asya.url").decode()

    payload.setdefault("a2a", {}).setdefault("task", {}).setdefault("artifacts", [])
    payload["a2a"]["task"]["artifacts"].append({
        "artifact_id": "rendered-video",
        "name": "Rendered Video",
        "parts": [
            {"url": url, "media_type": "video/mp4", "filename": "output.mp4"}
        ]
    })
    return payload
```

**No chunking in the artifact**. The artifact has one Part with one URL. The file
may be 2GB, but the Part in the envelope is ~80 bytes. Chunked/multipart upload
is handled at the storage transport level by the state proxy connector — the
actor sees a regular `open()`/`write()`.

**A2A client access**: The client receives the URL and downloads the file
directly from S3 (or via presigned URL for unauthenticated access). For very
large files, use `user.asya.presigned_url` to avoid requiring S3 credentials:

```python
presigned = os.getxattr("/state/artifacts/output.mp4", "user.asya.presigned_url").decode()
# → "https://bucket.s3.amazonaws.com/artifacts/output.mp4?X-Amz-Signature=..."
```

##### Scenario 3: Streaming Output (LLM Text + Progressive Artifacts)

For streaming scenarios (LLM token generation, progressive image rendering),
the actor uses the **FLY channel** (ABI yield protocol) for real-time SSE
delivery. Streamed chunks are **ephemeral** — they reach the client via SSE but
are NOT persisted in `payload.a2a.task.artifacts` or `task.history`.

**A2A protocol support**: The `TaskArtifactUpdateEvent` has `append: bool` and
`last_chunk: bool` — the spec's mechanism for streaming chunked artifacts:

```protobuf
message TaskArtifactUpdateEvent {
  string task_id = 1;
  string context_id = 2;
  Artifact artifact = 3;    // chunk content
  bool append = 4;          // true = append to prev artifact with same ID
  bool last_chunk = 5;      // true = final chunk
}
```

**Actor implementation** (generator handler with FLY):

```python
import os

def stream_analysis(payload):
    query = payload["query"]

    # --- Phase 1: Stream text tokens via FLY (ephemeral) ---
    # Each FLY event becomes a TaskArtifactUpdateEvent SSE event
    for token in llm.stream(query):
        yield "FLY", {
            "type": "artifact_update",
            "artifact": {
                "artifact_id": "live-analysis",
                "parts": [{"text": token}]
            },
            "append": True,
            "last_chunk": False
        }

    # Signal end of text stream
    yield "FLY", {
        "type": "artifact_update",
        "artifact": {
            "artifact_id": "live-analysis",
            "name": "Analysis",
            "parts": [{"text": ""}]
        },
        "append": True,
        "last_chunk": True
    }

    # --- Phase 2: Persist final result as URL artifact ---
    full_text = llm.get_full_response()
    with open("/state/artifacts/analysis.md", "w") as f:
        f.write(full_text)
    url = os.getxattr("/state/artifacts/analysis.md", "user.asya.url").decode()

    # This URL artifact is what persists in payload.a2a.task.artifacts
    payload.setdefault("a2a", {}).setdefault("task", {}).setdefault("artifacts", [])
    payload["a2a"]["task"]["artifacts"].append({
        "artifact_id": "analysis-final",
        "name": "Complete Analysis",
        "parts": [{"url": url, "media_type": "text/markdown",
                   "filename": "analysis.md"}]
    })
    yield payload
```

**Two channels, two lifecycles**:

| Channel | Transport | Persisted? | Purpose |
|---------|-----------|------------|---------|
| FLY (`yield "FLY"`) | SSE `artifact_update` events | No — ephemeral | Real-time streaming to connected clients |
| Payload artifacts | `payload.a2a.task.artifacts` | Yes — in envelope/S3 | Final result for `GetTask` responses |

**Gateway translation**: The sidecar forwards FLY events to the gateway via
`POST {base}/mesh/{id}/partial`. The gateway broadcasts them as SSE
`TaskArtifactUpdateEvent` to subscribed clients. When the task completes,
`GetTask` returns only the URL artifacts from `payload.a2a.task.artifacts` —
the streamed tokens are gone.

**Does streamed content need to be persisted?** No. The A2A spec explicitly
separates streaming events (`TaskArtifactUpdateEvent` in `StreamResponse`) from
the persisted task state (`Task.artifacts` in `GetTask`). Streaming events are
delivery-time-only. If a client connects after the stream ends, they get the
final artifacts via `GetTask`, not a replay of the stream. This matches how
SSE works in general — it's a live channel, not a recording.

**What if the client needs the full streamed text?** The actor persists it as a
final URL artifact (Phase 2 above). The stream gives real-time UX; the URL
artifact gives durable access. Both coexist.

### 5.4 History in Envelope Payload

`payload.a2a.task.history` stores `repeated Message` — the same schema as A2A
`Task.history`. Each entry is an A2A `Message` proto (JSON-serialized):

```protobuf
message Message {
  string message_id = 1;          // REQUIRED — unique per message
  string context_id = 2;          // optional — set by gateway
  string task_id = 3;             // optional — set by gateway
  Role role = 4;                  // REQUIRED — "user" or "agent"
  repeated Part parts = 5;        // REQUIRED — content
  Struct metadata = 6;            // optional
  repeated string extensions = 7; // optional
  repeated string reference_task_ids = 8; // optional
}
```

**Example**: full envelope payload with 3-turn history:

```json
{
  "a2a": {
    "task": {
      "id": "task-uuid",
      "context_id": "ctx-uuid",
      "history": [
        {
          "message_id": "m-001",
          "role": "user",
          "parts": [{"text": "Analyze this data"}]
        },
        {
          "message_id": "m-002",
          "role": "agent",
          "parts": [{"text": "I need more context. What aspect should I focus on?"}]
        },
        {
          "message_id": "m-003",
          "role": "user",
          "parts": [{"text": "Focus on revenue trends"}]
        }
      ],
      "metadata": {"skill": "analyze-doc"}
    }
  },
  "query": "Focus on revenue trends",
  "context": "Analyze this data"
}
```

**Why envelope payload, not gateway DB**:

- History travels with the envelope through the actor mesh. Actors that need
  multi-turn context can read `payload.a2a.task.history` directly.
- On pause (x-pause), the full envelope (including history) is persisted to S3.
  On resume (x-resume), history is restored with the envelope.
- The gateway does not store a separate copy of history.

**Implications for GetTask**:

- `GetTask(historyLength=N)` returns history from the envelope state.
- For **in-flight tasks**: history is in the queue message. Gateway **omits the
  `history` field entirely** (not `[]` — the field is absent). Streaming
  (SubscribeToTask) covers the real-time case.
- For **paused tasks**: history is in S3 (persisted by x-pause). Gateway
  fetches from S3 on demand and returns the last N messages.
- For **completed tasks**: history is in x-sink's S3 result. Gateway fetches
  from S3 on demand.
- A2A spec marks `history` as optional (`repeated Message`, not REQUIRED).
  Omitting it for in-flight tasks is spec-compliant.

### 5.5 Context as Grouping Attribute

`context_id` is a TEXT column on the `tasks` table with an index. It is NOT a
first-class entity — there is no `contexts` table, no context lifecycle, no
`CreateContext` operation.

**Behavior**:

- If `SendMessage` includes `message.context_id`: use it as-is. Associates the
  new task with that context.
- If `SendMessage` omits `context_id`: gateway generates a UUID.
  Context = single-task conversation.
- `ListTasks(context_id="c1")`: returns all tasks in that context.
- Multiple tasks in the same context are independent envelopes. They share only
  the grouping key.

**Cross-task context sharing**: If an actor needs to reference previous tasks'
results in the same context (e.g., multi-turn agent memory), it can use the state
proxy (RFC 1dmf) with `context_id` as a storage key. This is actor-level business
logic, not A2A protocol logic.

### 5.6 ID Scheme and Metadata Placement

**Task ID = Envelope ID** (same UUID). The gateway generates the ID and uses it
for both the task record and the envelope envelope. This is a convenience, not a
hard contract — consumers should NOT rely on `envelope.id` to obtain the A2A
task ID. Instead, read from the canonical locations below.

**A2A metadata is stored in TWO locations** (intentional duplication):

1. **`payload.a2a.task`** — canonical, self-contained, travels with the envelope
   through the pipeline. Actors read A2A data directly from payload:
   ```python
   context_id = payload["a2a"]["task"]["context_id"]
   history = payload["a2a"]["task"]["history"]
   ```

2. **`headers.x-asya-a2a-*`** — lightweight duplicate for sidecar access.
   The sidecar must not parse payload contents, so it reads from headers:
   ```json
   {
     "headers": {
       "x-asya-a2a-task-id": "task-uuid",
       "x-asya-a2a-context-id": "ctx-uuid"
     }
   }
   ```

| Data | `payload.a2a.task.*` | `headers.x-asya-a2a-*` | Gateway DB |
|------|---------------------|------------------------|------------|
| task_id | `.id` | `x-asya-a2a-task-id` | `tasks.id` |
| context_id | `.context_id` | `x-asya-a2a-context-id` | `tasks.context_id` |
| skill | `.metadata.skill` | — | — |
| history | `.history[]` | — | — |
| artifacts | `.artifacts[]` | — | — |
| status | — (stale, omitted) | — | `tasks.status` |

**Why duplicate**: Headers exist for sidecar (progress reporter, which needs
task_id for `POST /mesh/{id}/progress`). Payload exists for actors and for
self-containment (when persisted to S3, the envelope carries all A2A context).
Gateway DB exists for queries (ListTasks, GetTask metadata).

**Why `x-asya-a2a-*` prefix**: "Task" and "context" are A2A protocol concepts —
they should NOT exist outside the A2A layer. The `x-asya-a2a-` prefix makes this
boundary explicit. Asya-internal headers (like `x-asya-pause`, `x-asya-resume-task`)
keep the existing `x-asya-` prefix since they are not A2A-specific.

**Skill storage**: The skill name that was invoked lives in
`payload.a2a.task.metadata.skill` (not a header). The gateway reads it from the
persisted envelope when handling task continuation.

### 5.7 Dual-Channel Message Pattern

A2A Messages are modeled via two complementary channels depending on whether
they are transient signals or canonical records:

| Feature | FLY (Ephemeral) | Envelope History (Persistent) |
|---------|-----------------|------------------------------|
| **A2A semantic** | `StreamResponse` variants: `artifact_update`, `status_update`, `message` | A2A `Task.history` (`repeated Message`) |
| **Asya mechanism** | `yield "FLY", {...}` → runtime SSE → sidecar → `POST /mesh/{id}/partial` → gateway SSE | Appended to `payload.a2a.task.history[]` → travels through message queues |
| **Persistence** | None (real-time broadcast only) | Travels with envelope, survives pause/resume via S3 |
| **Primary use** | Streaming tokens, thoughts, live status, progress indicators | Multi-turn conversation history, final answers, input prompts |
| **Visibility** | Connected SSE clients only | All subsequent actors + late-joining clients (via S3 fetch) |
| **Storage cost** | Zero (fire-and-forget broadcast) | Grows per canonical turn (bounded by queue message size limit) |
| **When to use** | Actor wants to show progress, stream tokens, signal thinking | Actor needs to record a turn that future actors or resume cycles can read |

**Rule of thumb**: If the data matters after the SSE connection closes, put it in
`payload.a2a.task.history`. If it's only useful while watching in real-time, use FLY.

**FLY channel example** (actor code):

```python
async def agent_actor(payload):
    # Stream tokens via FLY — ephemeral, not persisted
    async for token in model.stream(payload["query"]):
        yield "FLY", {"artifact_update": {
            "artifact": {"artifact_id": "stream-0",
                         "parts": [{"text": token}]},
            "append": True, "last_chunk": False
        }}

    # Record canonical turn in history — persisted
    result = await model.complete(payload["query"])
    payload.setdefault("a2a", {}).setdefault("task", {}).setdefault("history", [])
    payload["a2a"]["task"]["history"].append({
        "role": "agent",
        "parts": [{"text": result}]
    })

    payload["response"] = result
    yield payload  # EMIT downstream
```

---

## 6. Gateway Architecture

### 6.1 Endpoint Layout

All routes (except `/.well-known/agent.json` and `/health`) live under three
fixed namespaces with an optional base prefix:

```
ASYA_BASE_PREFIX=""          →  /a2a/..., /mcp/..., /mesh/...
ASYA_BASE_PREFIX="/api/v1"   →  /api/v1/a2a/..., /api/v1/mcp/..., /api/v1/mesh/...
```

| Env Var | Purpose | Default |
|---------|---------|---------|
| `ASYA_BASE_PREFIX` | Base prefix for all namespaced routes | `""` (empty) |

**Full endpoint map** (with `{base}` = `ASYA_BASE_PREFIX`):

```
asya-gateway
│
│  A2A namespace (/a2a) — client-facing, A2A protocol
├── {base}/a2a/message:send                                # SendMessage (POST)
├── {base}/a2a/message:stream                              # SendStreamingMessage (POST, SSE)
├── {base}/a2a/tasks/{id}                                  # GetTask (GET)
├── {base}/a2a/tasks                                       # ListTasks (GET)
├── {base}/a2a/tasks/{id}:cancel                           # CancelTask (POST)
├── {base}/a2a/tasks/{id}:subscribe                        # SubscribeToTask (GET, SSE)
├── {base}/a2a/tasks/{id}/pushNotificationConfigs          # Push CRUD
├── {base}/a2a/tasks/{id}/pushNotificationConfigs/{cfgId}  # Push Get/Delete
├── {base}/a2a/extendedAgentCard                           # GetExtendedAgentCard (GET)
│
│  MCP namespace (/mcp) — client-facing, MCP protocol
├── {base}/mcp                           # MCP Streamable HTTP (POST)
├── {base}/mcp/sse                       # MCP SSE deprecated (GET)
├── {base}/mcp/tools/call                # REST tool invocation (POST)
│
│  Mesh namespace (/mesh) — internal, sidecar + management
├── {base}/mesh/expose                   # Register tool/skill (POST), list (GET)
├── {base}/mesh/{id}/progress            # Sidecar progress reporting (POST)
├── {base}/mesh/{id}/final               # End actor final status (POST)
├── {base}/mesh/{id}/active              # Sidecar liveness check (GET)
├── {base}/mesh/{id}/stream              # SSE streaming (GET, internal)
├── {base}/mesh/{id}/partial             # Partial event payload (POST)
├── {base}/mesh                          # Sidecar registers fanout child tasks (POST)
│
│  Root (no prefix, not affected by ASYA_BASE_PREFIX)
├── /.well-known/agent.json              # Agent Card discovery (GET, A2A spec requires root)
└── /health                              # Health check (GET, K8s probes need fixed path)
```

**Three namespaces, clean separation**:

| Namespace | Audience | Auth | Purpose |
|-----------|----------|------|---------|
| `/a2a` | External AI agents, orchestrators | A2A auth middleware | A2A protocol surface |
| `/mcp` | LLMs, developers, tool-calling clients | MCP auth (future) | MCP protocol surface |
| `/mesh` | Sidecars, operators, CLI | Internal (network-level) | Actor mesh management |

**Design decisions**:
- A2A paths follow the protobuf HTTP annotations (`/message:send`,
  `/tasks/{id}:cancel`). No collision with `/mesh/{id}/*` (internal).
- MCP tool invocation moves from `/tools/call` to `/mcp/tools/call` for
  namespace consistency.
- `POST /mesh/expose` is the only registration endpoint — no per-tool
  GET/DELETE. To remove a tool, POST with `"enabled": false` (soft delete)
  or add `DELETE /mesh/expose/{name}` if hard delete is needed later.
- `/.well-known/agent.json` is ALWAYS at root regardless of base prefix
  (A2A spec requirement).

### 6.2 a2a-go Library Integration

The gateway imports the official A2A Go library:

```go
import (
    "github.com/a2aproject/a2a-go/a2a"      // Core types
    "github.com/a2aproject/a2a-go/a2asrv"    // Server framework
)
```

**What a2a-go provides**:

| Package | Provides | Replaces |
|---------|----------|----------|
| `a2a` | `Task`, `Message`, `Part`, `Artifact`, `AgentCard`, `AgentSkill`, `TaskState`, `StreamResponse`, all request/response types | Hand-rolled types in `internal/a2a/types.go` |
| `a2asrv` | `NewHandler()`, `NewJSONRPCHandler()`, JSON-RPC dispatch, SSE formatting, request validation | Hand-rolled JSON-RPC dispatch in `internal/a2a/handler.go` |
| `a2asrv` | `AgentExecutor` interface | N/A (new) |
| `a2asrv` | `TaskStore` interface | Wraps existing `taskstore.TaskStore` |

**What Asya implements**:

| Interface | Asya Implementation | Purpose |
|-----------|-------------------|---------|
| `a2asrv.AgentExecutor` | `internal/a2a/executor.go` | Translates A2A Messages → envelopes, dispatches to queue |
| `a2asrv.TaskStore` | `internal/a2a/store_adapter.go` | Wraps `taskstore.PgStore`, translates between internal and A2A types |

### 6.3 AgentExecutor Implementation

The `AgentExecutor` is the core bridge between A2A and the actor mesh:

```go
// internal/a2a/executor.go

type AsyaExecutor struct {
    queueClient   queue.Client
    taskStore     taskstore.TaskStore
    skillRegistry *SkillRegistry
    namespace     string
}

func (e *AsyaExecutor) Execute(
    ctx context.Context,
    reqCtx *a2asrv.RequestContext,
    queue eventqueue.Queue,
) error {
    msg := reqCtx.Message()
    taskInfo := reqCtx.TaskInfo()

    // 1. Resolve skill → entrypoint actor
    skill, err := e.resolveSkill(msg)
    if err != nil {
        return e.writeRejection(queue, taskInfo, err)
    }

    // 2. Translate A2A Message → envelope payload
    payload := messageToPayload(msg)

    // 3. Set A2A task status snapshot in payload (REQUIRED by proto)
    payload["a2a"].(map[string]any)["task"].(map[string]any)["status"] = map[string]any{
        "state":     "submitted",
        "timestamp": time.Now().UTC().Format(time.RFC3339),
    }

    // 4. Create envelope with A2A metadata in headers
    envelope := &types.Task{
        ID:        string(taskInfo.TaskID),
        ContextID: taskInfo.ContextID,
        Status:    types.TaskStatusPending,
        Route: types.Route{
            Prev: []string{},
            Curr: skill.Actor,
            Next: []string{},
        },
        Headers: map[string]any{
            "x-asya-a2a-task-id":    string(taskInfo.TaskID),
            "x-asya-a2a-context-id": taskInfo.ContextID,
        },
        Payload: payload,
    }

    // 5. Dispatch to actor queue
    if err := e.queueClient.SendMessage(ctx, envelope); err != nil {
        return e.writeFailure(queue, taskInfo, err)
    }

    // 6. Write initial "submitted" event
    return queue.Write(ctx, &a2a.TaskStatusUpdateEvent{
        TaskID:    taskInfo.TaskID,
        ContextID: taskInfo.ContextID,
        Status: a2a.TaskStatus{
            State:     a2a.TaskStateSubmitted,
            Timestamp: timePtr(time.Now()),
        },
    })
}

func (e *AsyaExecutor) Cancel(
    ctx context.Context,
    reqCtx *a2asrv.RequestContext,
    queue eventqueue.Queue,
) error {
    taskID := reqCtx.TaskInfo().TaskID

    // Mark task as canceled in internal store
    err := e.taskStore.Update(types.TaskUpdate{
        ID:     string(taskID),
        Status: types.TaskStatusCanceled,
    })
    if err != nil {
        return err
    }

    // Write cancellation event
    return queue.Write(ctx, &a2a.TaskStatusUpdateEvent{
        TaskID:    taskID,
        ContextID: reqCtx.TaskInfo().ContextID,
        Status: a2a.TaskStatus{
            State:     a2a.TaskStateCanceled,
            Timestamp: timePtr(time.Now()),
        },
    })
}
```

**Resume handling**: When `SendMessage` includes a `task_id` referencing a paused
task, the executor detects this and dispatches to x-resume instead:

```go
func (e *AsyaExecutor) Execute(ctx, reqCtx, queue) error {
    msg := reqCtx.Message()

    // Check if this is a resume (message has task_id and task is paused)
    if msg.TaskID != "" {
        task, err := e.taskStore.Get(string(msg.TaskID))
        if err == nil && task.Status == types.TaskStatusPaused {
            return e.handleResume(ctx, reqCtx, queue, task, msg)
        }
    }

    // Normal execution (new task)
    return e.handleNewTask(ctx, reqCtx, queue, msg)
}
```

### 6.4 TaskStore Adapter

The `a2asrv.TaskStore` interface wraps the existing `taskstore.TaskStore`:

```go
// internal/a2a/store_adapter.go

type A2AStoreAdapter struct {
    internal taskstore.TaskStore
}

func (a *A2AStoreAdapter) Save(
    ctx context.Context,
    task *a2a.Task,
    event a2a.Event,
    prev a2a.TaskVersion,
) (a2a.TaskVersion, error) {
    // Translate a2a.Task → types.TaskUpdate
    update := a2aTaskToUpdate(task, event)
    err := a.internal.Update(update)
    // Return new version (timestamp-based)
    return a2a.TaskVersion(task.Status.Timestamp.UnixNano()), err
}

func (a *A2AStoreAdapter) Get(
    ctx context.Context,
    taskID a2a.TaskID,
) (*a2a.Task, a2a.TaskVersion, error) {
    task, err := a.internal.Get(string(taskID))
    if err != nil {
        return nil, 0, a2a.ErrTaskNotFound
    }
    a2aTask := internalToA2ATask(task)
    version := a2a.TaskVersion(task.UpdatedAt.UnixNano())
    return a2aTask, version, nil
}

func (a *A2AStoreAdapter) List(
    ctx context.Context,
    req *a2a.ListTasksRequest,
) (*a2a.ListTasksResponse, error) {
    // Translate filters and delegate to internal store
    // Internal store needs new List method with pagination
}
```

---

## 7. A2A Service Methods

### 7.1 SendMessage

**Method**: `message/send`
**HTTP**: `POST {base}/a2a/message:send`

**Flow**:

1. Parse `SendMessageRequest` (handled by a2a-go)
2. Extract `Message` and optional `SendMessageConfiguration`
3. If `message.task_id` set and task is paused → resume flow (Section 10.3)
4. If `message.task_id` set and task is not paused → append to existing task
5. If no `task_id` → resolve skill, create new task, dispatch envelope
6. If `configuration.blocking == true` → hold connection until terminal/interrupted
7. Return `SendMessageResponse` with Task (or Message for quick responses)

**Response modes**:

| Mode | Behavior | When |
|------|----------|------|
| Non-blocking (default) | Return Task immediately with `status: submitted` | Always, unless blocking requested |
| Blocking | Hold HTTP connection, return Task with terminal status | `configuration.blocking: true` |

**Error conditions**:

| Error | Code | When |
|-------|------|------|
| Skill not found | `-32001` | No matching skill and no default |
| Task not found | `-32002` | `task_id` references nonexistent task |
| Content type unsupported | `-32003` | Parts contain unsupported media types |
| Invalid params | `-32602` | Missing required fields |

### 7.2 SendStreamingMessage

**Method**: `message/stream`
**HTTP**: `POST {base}/a2a/message:stream`

Same as SendMessage but returns an SSE stream instead of a single response.

**SSE event sequence**:

```
event: task
data: {"id":"t-1","contextId":"c-1","status":{"state":"SUBMITTED",...}}

event: status_update
data: {"taskId":"t-1","contextId":"c-1","status":{"state":"WORKING",...}}

event: artifact_update
data: {"taskId":"t-1","contextId":"c-1","artifact":{...},"append":true,"lastChunk":false}

event: artifact_update
data: {"taskId":"t-1","contextId":"c-1","artifact":{...},"lastChunk":true}

event: status_update
data: {"taskId":"t-1","contextId":"c-1","status":{"state":"COMPLETED",...}}
```

**Implementation**: The a2a-go handler subscribes to the `eventqueue.Queue` and
translates events to SSE. The gateway feeds events from:

1. Task creation → `task` event
2. Sidecar progress reports → `status_update` events
3. FLY events from actors → `artifact_update` or `status_update` or `message`
4. x-sink final report → `artifact_update` (last chunk) + `status_update` (terminal)

### 7.3 GetTask

**Method**: `tasks/get`
**HTTP**: `GET {base}/a2a/tasks/{id}`

Returns the current state of a task.

**Parameters**:

- `id` (REQUIRED): Task ID
- `history_length` (optional): Max number of history messages to return

**Response**: `a2a.Task` with status, and optionally artifacts and history.

**History retrieval** (since history lives in envelope payload):

- In-flight tasks: `history` field **omitted** (not available from queues)
- Paused tasks: Fetch from S3 (persisted by x-pause), return last N messages
- Completed tasks: Fetch from S3 (persisted by x-sink), return last N messages
- If S3 fetch fails: `history` field **omitted** (field is optional per spec)

**Artifact retrieval** (since artifacts live in envelope payload):

- Same S3 fetch mechanism as history. When `include_artifacts=true`, gateway
  reads `payload.a2a.task.artifacts` from S3 result.

### 7.4 ListTasks

**Method**: `tasks/list`
**HTTP**: `GET {base}/a2a/tasks`

**Parameters**:

| Param | Type | Description |
|-------|------|-------------|
| `context_id` | string | Filter by context |
| `status` | TaskState | Filter by state |
| `page_size` | int | Items per page (default 50, max 100) |
| `page_token` | string | Cursor for next page |
| `history_length` | int | Messages per task (default 0) |
| `status_timestamp_after` | timestamp | Filter by status update time |
| `include_artifacts` | bool | Include artifacts (default false) |

**Implementation**: Requires new `List` method on internal TaskStore with
cursor-based pagination. PostgreSQL query uses `LIMIT/OFFSET` with `WHERE`
clauses.

### 7.5 CancelTask

**Method**: `tasks/cancel`
**HTTP**: `POST {base}/a2a/tasks/{id}:cancel`

**Flow**:

1. Validate task exists and is not in terminal state
2. Set task status to `canceled` in TaskStore (DB — authoritative)
3. Return updated Task with `status.state: CANCELED` to client immediately
4. Sidecar discovers cancellation on next `GET /mesh/{id}/active` → `410 Gone`
5. Sidecar drops the envelope, persists it, and reports final status

**Race condition**: The envelope may be in a queue, being processed by an actor,
or waiting to be picked up. The gateway cannot modify messages already in queues.
The sidecar's `GET /mesh/{id}/active` check is the handshake that resolves this:

**Cancellation flow — envelope in queue (not yet picked up)**:

```
Client                     Gateway              Sidecar               Queue
  |                          |                     |                    |
  |-- POST :cancel --------->|                     |                    |
  |                          |-- DB: status =      |                    |
  |                          |   "canceled"        |                    |
  |<-- Task{CANCELED} -------|                     |                    |
  |                          |                     |                    |
  |                     (later: sidecar picks up message from queue)    |
  |                          |                     |<-- receive msg ----|
  |                          |                     |                    |
  |                          |                     |-- POST /mesh/{id}/ |
  |                          |<-------- progress (status: received) ----|
  |                          |--- 410 Gone ------->|                    |
  |                          |                     |                    |
  |                          |                     |-- Ack msg          |
  |                          |                     |   (prevent DLQ)    |
  |                          |                     |-- Persist envelope  |
  |                          |                     |   to x-sink queue  |
  |                          |                     |   (for S3 record)  |
  |                          |                     |-- Do NOT call      |
  |                          |                     |   runtime          |
```

**Cancellation flow — envelope being processed by actor**:

```
Client                     Gateway              Sidecar               Runtime
  |                          |                     |                    |
  |                          |                     |-- POST /mesh/{id}/ |
  |                          |<-- progress (received) --|               |
  |                          |--- 200 OK (active) -->|                  |
  |                          |                     |-- Forward to ----->|
  |                          |                     |   runtime          |
  |                          |                     |                    |
  |-- POST :cancel --------->|                     |     (processing)   |
  |                          |-- DB: status =      |                    |
  |                          |   "canceled"        |                    |
  |<-- Task{CANCELED} -------|                     |                    |
  |                          |                     |                    |
  |                          |                     |<-- response -------|
  |                          |                     |                    |
  |                          |                     |-- POST /mesh/{id}/ |
  |                          |<-- progress (completed) --|              |
  |                          |--- 410 Gone ------->|                    |
  |                          |                     |                    |
  |                          |                     |-- Ack msg          |
  |                          |                     |-- Persist envelope  |
  |                          |                     |   to x-sink queue  |
  |                          |                     |-- Do NOT route     |
  |                          |                     |   to next actor    |
```

**Sidecar behavior on cancellation** (discovered via progress report → `410 Gone`):

1. **On progress report**: Sidecar sends `POST /mesh/{id}/progress` with
   `status: received` when it picks up a message. If gateway returns `410 Gone`
   instead of `200 OK`, the task is no longer active (canceled, completed, or
   failed).

2. **Before runtime call**: If `410` is received on the initial "received"
   progress report, sidecar MUST NOT call the runtime. Instead:
   - Ack the message (prevent DLQ pollution)
   - Route to x-sink queue for S3 persistence (preserves envelope for audit)
   - Log cancellation at INFO level

3. **After runtime call**: If `410` is received on the "completed" progress
   report (meaning cancellation happened during processing), sidecar:
   - Ack the message
   - Route result to x-sink queue (preserves the work done)
   - Do NOT route to the next actor in the pipeline
   - The runtime's work is not wasted — it's persisted for potential replay

4. **No runtime changes**: Cancellation is transparent to actors. The runtime
   handler runs to completion if already started — the sidecar decides not to
   route further.

**Progress reporter response codes**:

| Response | Meaning | Sidecar action |
|----------|---------|----------------|
| `200 OK` | Task is active | Continue processing normally |
| `410 Gone` | Task is inactive (canceled/completed/failed) | Drop, persist, don't route |
| `5xx` / timeout | Gateway unreachable | Continue processing (fail-open) |

**Why fail-open on 5xx**: If the gateway is temporarily unreachable, the sidecar
should continue processing rather than dropping the message (fail-safe over fail-fast).
The envelope is already dequeued — dropping it would lose work. Better to process and
let the next progress report discover the cancellation.

**Error**: `TaskNotCancelableError` if task is already in terminal state.

### 7.6 SubscribeToTask

**Method**: `tasks/subscribe`
**HTTP**: `GET {base}/a2a/tasks/{id}:subscribe`

SSE stream for an existing task. Same event format as SendStreamingMessage.

**Behavior**:

1. If task is in terminal state: return `UnsupportedOperationError`
2. Replay historical events (from `task_updates` table)
3. Subscribe to live events via TaskStore pub/sub
4. Stream until terminal state, then close SSE connection
5. Send keepalive comments (`: keepalive\n\n`) every 15 seconds

### 7.7 Push Notification CRUD

Four methods for managing webhook-based push notifications:

| Method | HTTP | Purpose |
|--------|------|---------|
| `CreateTaskPushNotificationConfig` | `POST {base}/a2a/tasks/{id}/pushNotificationConfigs` | Register webhook |
| `GetTaskPushNotificationConfig` | `GET {base}/a2a/tasks/{id}/pushNotificationConfigs/{cfgId}` | Get config |
| `ListTaskPushNotificationConfigs` | `GET {base}/a2a/tasks/{id}/pushNotificationConfigs` | List configs |
| `DeleteTaskPushNotificationConfig` | `DELETE {base}/a2a/tasks/{id}/pushNotificationConfigs/{cfgId}` | Remove |

**Push delivery**: When a task update occurs and push configs exist, the gateway
POSTs the event to the registered webhook URL with the configured authentication
headers.

**Database**: New `task_push_configs` table (see Section 13).

**Implementation phase**: Phase 4 (deferred). The a2a-go handler returns
`PushNotificationNotSupportedError` until implemented. The Agent Card declares
`capabilities.push_notifications: false`.

### 7.8 GetExtendedAgentCard

**Method**: `extendedAgentCard`
**HTTP**: `GET {base}/a2a/extendedAgentCard`

Returns an authenticated, extended version of the Agent Card with additional
details not publicly visible.

**Implementation phase**: Phase 3. Returns `UnsupportedOperationError` initially.
The Agent Card declares `capabilities.extended_agent_card: false`.

---

## 8. Agent Card and Skill Discovery

### 8.1 Agent Card Structure

Served at `GET /.well-known/agent.json`. Generated dynamically from the
`tools` table (skills with `a2a_enabled = true`).

```json
{
  "name": "Asya Gateway",
  "description": "AI Actor Mesh for distributed agentic workloads",
  "version": "1.0.0",
  "provider": {
    "organization": "Asya",
    "url": "https://asya.sh"
  },
  "supportedInterfaces": [
    {
      "url": "https://gateway.example.com/message:send",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ],
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "extendedAgentCard": false
  },
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"],
  "skills": [
    {
      "id": "analyze-document",
      "name": "Document Analysis",
      "description": "Analyze documents for key themes and sentiment",
      "tags": ["analysis", "nlp", "documents"],
      "inputModes": ["application/json", "application/pdf"],
      "outputModes": ["application/json"],
      "examples": ["Analyze this quarterly report for revenue trends"]
    }
  ],
  "securitySchemes": {},
  "securityRequirements": []
}
```

**Configuration**:

| Env Var | Purpose | Default |
|---------|---------|---------|
| `ASYA_A2A_NAME` | Agent name in card | `"Asya Gateway"` |
| `ASYA_A2A_DESCRIPTION` | Agent description | `"AI Actor Mesh"` |
| `ASYA_A2A_VERSION` | Agent version | Build version |
| `ASYA_A2A_PUBLIC_URL` | Base URL for `supportedInterfaces` | Required |

**Refresh**: Agent Card is regenerated from the `tools` table whenever the tool
registry changes (POST/DELETE on `/mesh/expose`). Cached in memory via atomic
pointer swap.

### 8.2 Skill Registration

#### MCP Tool vs A2A Skill

MCP tools and A2A skills share the same backing data (entrypoint actor, route,
description) but serve **different consumers** with **different semantics**:

| Aspect | MCP Tool | A2A Skill |
|--------|----------|-----------|
| **Consumer** | LLMs doing tool-calling, developers | External AI agents, orchestrators |
| **Invocation** | Explicit tool name + structured parameters | Natural language message routed to skill |
| **Discovery** | `tools/list` JSON-RPC method | Agent Card at `/.well-known/agent.json` |
| **Parameters** | JSON Schema with required/optional fields | Freeform Message with Parts |
| **Response** | Task ID + status URL | Task object with status, artifacts, history |

**Opt-in model**: Exposing a flow as an MCP tool does NOT automatically make it
an A2A skill. Skills require **explicit opt-in** via `a2a_enabled = true`.

**Rationale**: A2A skills need additional metadata (tags, examples, input/output
modes) that MCP tools don't have. Not all tools make sense as A2A skills — some
are fine-grained operations meant for tool-calling LLMs, not for agent-to-agent
communication.

```sql
-- MCP tool only (default)
INSERT INTO tools (name, actor, description)
VALUES ('extract-text', 'text-extractor', 'Extract text from PDF');

-- Both MCP tool AND A2A skill (explicit opt-in)
INSERT INTO tools (name, actor, description, a2a_enabled, a2a_tags, a2a_examples)
VALUES ('analyze-document', 'start-analysis', 'Analyze documents for themes',
        true, '{"analysis","nlp","documents"}',
        '{"Analyze this quarterly report for revenue trends"}');
```

**CLI**:
```bash
# Expose as MCP tool only
asya flow expose my_flow.py --name extract-text

# Expose as both MCP tool + A2A skill
asya flow expose my_flow.py \
  --name analyze-document \
  --description "Analyze documents for themes" \
  --a2a \
  --a2a-tags analysis,nlp,documents \
  --a2a-examples "Analyze this quarterly report for revenue trends"
```

### 8.3 Skill Resolution Strategy

When a client sends `SendMessage`, the gateway must determine which skill
(entrypoint actor) to invoke. This is the A2A equivalent of MCP's explicit
`tools/call` routing.

**Resolution order**:

1. **Explicit skill hint**: `request.metadata["skill"]` names the skill ID.
   Exact match against `tools.name WHERE a2a_enabled = true`.

2. **Task continuation**: `message.task_id` is set → look up the original task's
   skill from persisted envelope `payload.a2a.task.metadata.skill`.

3. **Single skill default**: If exactly one A2A skill is registered, use it.
   Common for single-purpose gateways.

4. **Reject with guidance**: If multiple skills and no hint → return error with
   message listing available skills: `"Skill not specified. Available: [list]"`.

#### 8.3.1 LLM Router Pattern (Future)

For gateways with many skills, an **LLM router actor** can serve as the single
entrypoint skill. The router receives all A2A messages, uses an LLM to classify
intent, and dynamically routes to the appropriate skill flow:

```
SendMessage → Gateway → LLM Router Actor → [decides] → target skill flow
```

The LLM router can also decide to respond **directly with a Message** (no task
created for trivial queries) by:
1. Processing the message
2. Sending the response to the gateway via FLY as a `StreamResponse.message`
3. Completing the envelope (route exhausted → x-sink)

The A2A spec's `SendMessageResponse` allows returning either a `Task` or a
`Message`. For the LLM router pattern, the gateway always creates a Task
initially (Asya is fundamentally async), but the router can complete the task
immediately and the response appears synchronous to the client when
`configuration.blocking: true` is used.

**This pattern is not in initial scope** — it requires the LLM router actor to
be designed and the gateway to support `blocking` mode first (Phase 2).

### 8.4 Registration API

Tool/skill registration replaces the former YAML-based static config
(`routes.yaml` ConfigMap) with a DB-backed registry and REST API. The gateway
boots from PostgreSQL. No ConfigMap, no fsnotify, no gateway restart needed.

**Design decision**: Registration lives under `/mesh/expose` — an internal
management operation for the actor mesh, same namespace as sidecar-facing routes.
MCP tool invocation lives at `/mcp/tools/call`. A2A endpoints at `/a2a/*`.

#### 8.4.1 Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `{base}/mesh/expose` | Register or update a tool/skill (upsert) |
| `GET` | `{base}/mesh/expose` | List all registered tools/skills |

No per-tool GET/DELETE endpoints. To remove a tool, POST with
`"mcp_enabled": false, "a2a": {"enabled": false}` (soft disable). Hard delete
can be added later if needed via `DELETE {base}/mesh/expose/{name}`.

#### 8.4.2 Register (Upsert)

```http
POST {base}/mesh/expose
Content-Type: application/json

{
  "name": "analyze-document",
  "actor": "start-analysis",
  "description": "Analyze documents for key themes and sentiment",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Analysis query"},
      "depth": {"type": "integer", "default": 1}
    },
    "required": ["query"]
  },
  "timeout_sec": 300,
  "progress": true,
  "mcp_enabled": true,
  "a2a": {
    "enabled": true,
    "tags": ["analysis", "nlp", "documents"],
    "input_modes": ["application/json", "application/pdf"],
    "output_modes": ["application/json"],
    "examples": ["Analyze this quarterly report for revenue trends"]
  }
}
```

**Response**: `201 Created` (new) or `200 OK` (updated).

```json
{
  "name": "analyze-document",
  "actor": "start-analysis",
  "description": "Analyze documents for key themes and sentiment",
  "mcp_enabled": true,
  "a2a_enabled": true,
  "created_at": "2026-03-02T10:00:00Z",
  "updated_at": "2026-03-02T10:00:00Z"
}
```

#### 8.4.3 List

```http
GET {base}/mesh/expose

Response: 200 OK
[
  {"name": "analyze-document", "actor": "start-analysis", "mcp_enabled": true, "a2a_enabled": true},
  {"name": "extract-text", "actor": "text-extractor", "mcp_enabled": true, "a2a_enabled": false}
]
```

#### 8.4.4 In-Memory Registry Refresh

After each mutation (POST/DELETE), the gateway reloads the full tool list from
DB into an in-memory registry. Thread-safe via `atomic.Value` (Go). In-flight
requests complete with the old registry; new requests use the updated one.

```go
// Follows existing TaskStore pattern
type ToolRegistry struct {
    tools atomic.Value // *[]Tool
    db    *sql.DB
}

func (r *ToolRegistry) Refresh() error {
    tools, err := r.loadFromDB()
    if err != nil { return err }
    r.tools.Store(&tools)
    return nil
}
```

Both MCP and A2A read from the same registry:
- MCP `tools/list`: filter `WHERE mcp_enabled = true`
- A2A Agent Card skills: filter `WHERE a2a_enabled = true`

#### 8.4.5 Route Simplification (CPS)

With DB-backed registration, the gateway sends to the **entrypoint actor only**,
not a full route list. Routing decisions are made by router actors at each step
(Continuation-Passing Style):

```
Before (YAML config):    route: [validator, processor, notifier]
After (DB + CPS):         actor: start-order-processing
```

The `start-order-processing` router writes the actual continuation via ABI:
```python
yield "SET", ".route.next", ["validator", "processor", "notifier"]
yield payload
```

A tool maps to exactly **one entrypoint actor**. Standalone actors with empty
`next` are just entrypoints with no continuation.

#### 8.4.6 YAML Config Migration

The YAML-based tool config (`routes.yaml` ConfigMap) is fully replaced:

**Removed**:
- `config.LoadConfig()` from `main.go`
- `ASYA_CONFIG_PATH` env var
- `routes-configmap.yaml` from Helm chart
- `config/routes.go` route template resolution

**Migration path**: CLI migration script (Phase 2):
```bash
asya tools migrate --from routes.yaml --gateway-url http://...
```
Reads YAML, POSTs each tool to the gateway API. Explicit, auditable.

---

## 9. Streaming Architecture

### 9.1 FLY to A2A StreamResponse Mapping

Actors emit FLY events in **A2A-native StreamResponse format**. The dict yielded
by FLY is the StreamResponse payload directly:

```python
# Actor code: token streaming
yield "FLY", {
    "artifact_update": {
        "artifact": {
            "artifact_id": "stream-0",
            "parts": [{"text": "analyzing the "}]
        },
        "append": True,
        "last_chunk": False
    }
}

# Actor code: status/thinking update
yield "FLY", {
    "status_update": {
        "status": {
            "state": "WORKING",
            "message": {
                "role": "agent",
                "parts": [{"text": "Processing document..."}]
            }
        }
    }
}

# Actor code: direct message
yield "FLY", {
    "message": {
        "role": "agent",
        "parts": [{"text": "I found 3 key themes."}]
    }
}

# Or using a2a python package like a2a-sdk (or a2a-python):
from a2a.types import Message, Role
yield "FLY", {"message": Message(id="123", role=Role.agent, ...)}
```

Note: we need to implement automatic serialization pydantic models and typed dicts as part of `dict` into json objects - currently if we do `json.dumps` on the last example it'll throw `not JSON serializable` error. For now, a workaround would be:

```py
from a2a.types import Message, Role
yield "FLY", {"message": Message(id="123", role=Role.agent, ...).model_dump(mode="json")}

```

**Runtime behavior**: The runtime passes the FLY dict to the sidecar unchanged
(it never inspects FLY payload contents — ABI invariant #5). The sidecar forwards
to the gateway. The gateway broadcasts to SSE subscribers.

**Note on ADK compatibility**: ADK (Google's Agentic Development Kit) uses
`partial: True` on LLM streaming responses. This is a framework-level convention,
not an Asya ABI concept. Asya moved from `partial: True` to FLY to separate
control plane (tuple dispatch) from data plane (dict contents). There is no
conflict: FLY is the transport mechanism, and the A2A-native dict content is the
semantic payload.

**Runtime helpers** (optional, in `asya_runtime.py`):

```python
# Zero-dependency helpers for common FLY patterns
def fly_text(text, artifact_id="stream-0", last=False):
    """Convenience: yield "FLY", fly_text("hello")"""
    return {
        "artifact_update": {
            "artifact": {"artifact_id": artifact_id, "parts": [{"text": text}]},
            "append": True,
            "last_chunk": last,
        }
    }

def fly_status(message):
    """Convenience: yield "FLY", fly_status("Thinking...")"""
    return {
        "status_update": {
            "status": {
                "state": "WORKING",
                "message": {"role": "agent", "parts": [{"text": message}]},
            }
        }
    }
```

### 9.2 SSE Event Format

A2A streaming uses SSE with events matching `StreamResponse` oneof variants:

```
event: task
data: {"id":"t-1","contextId":"c-1","status":{"state":"SUBMITTED",...},"artifacts":[],"history":[]}

event: status_update
data: {"taskId":"t-1","contextId":"c-1","status":{"state":"WORKING","message":{"role":"agent","parts":[{"text":"Processing..."}]},"timestamp":"2026-03-02T10:00:00Z"}}

event: artifact_update
data: {"taskId":"t-1","contextId":"c-1","artifact":{"artifactId":"stream-0","parts":[{"text":"analyzing"}]},"append":true,"lastChunk":false}

event: status_update
data: {"taskId":"t-1","contextId":"c-1","status":{"state":"COMPLETED","timestamp":"2026-03-02T10:00:30Z"}}
```

**Keepalive**: `: keepalive\n\n` (SSE comment) every 15 seconds.

**JSON field names**: camelCase per A2A JSON convention (protobuf JSON mapping).
The a2a-go library handles serialization.

### 9.3 Actor-to-Client Streaming Flow

```
Actor                Runtime              Sidecar              Gateway              Client
  |                    |                    |                    |                    |
  |-- yield "FLY",{} ->|                    |                    |                    |
  |                    |-- upstream SSE --->|                    |                    |
  |                    |                    |-- POST             |                    |
  |                    |                    |   /mesh/{id}/      |                    |
  |                    |                    |   partial -------->|                    |
  |                    |                    |                    |-- SSE event ------->|
  |                    |                    |                    |  (artifact_update   |
  |                    |                    |                    |   or status_update  |
  |                    |                    |                    |   or message)       |
```

The gateway receives FLY events on `POST /mesh/{id}/partial`, detects the
StreamResponse variant from the dict keys (`artifact_update`, `status_update`,
or `message`), stamps `taskId` and `contextId`, and broadcasts to SSE subscribers.

### 9.4 Blocking Mode

When `configuration.blocking: true`, the gateway holds the HTTP connection:

1. Create task and dispatch envelope (same as non-blocking)
2. Subscribe to task events internally
3. Wait until task reaches terminal state (`COMPLETED`, `FAILED`, `CANCELED`,
   `REJECTED`) or interrupted state (`INPUT_REQUIRED`, `AUTH_REQUIRED`)
4. Return the final `Task` object with artifacts

**Timeout**: Uses the task's `timeout_sec` as the HTTP response timeout. If the
task times out, the gateway returns the task with `status: FAILED`.

**Blocking mode response** (example):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "task": {
      "id": "task-789",
      "contextId": "ctx-abc",
      "status": {
        "state": "COMPLETED",
        "timestamp": "2026-03-02T10:00:30Z"
      },
      "artifacts": [{
        "artifactId": "result-1",
        "parts": [{"url": "s3://bucket/results/analysis.json",
                   "mediaType": "application/json",
                   "filename": "analysis.json"}]
      }]
    }
  }
}
```

### 9.5 Multi-Frame Streaming Pipeline

Generator handlers communicate with the sidecar via an SSE-based multi-frame
protocol. This is the low-level transport that enables FLY streaming.

#### 9.5.1 Runtime → Sidecar Protocol

When a handler uses `yield` (generator), the runtime switches from batch JSON
response to SSE streaming with four event types:

| SSE Event Type | When | Content |
|----------------|------|---------|
| `event: downstream` | Handler yields a payload dict (EMIT) | `{"payload": {...}, "route": {...}}` — routed to next actor |
| `event: upstream` | Handler yields `"FLY", {...}` | `{"payload": {...}}` — forwarded to gateway for SSE broadcast |
| `event: error` | Handler raises exception | `{"error": "...", "traceback": "..."}` |
| `event: done` | Generator exhausted | Empty — signals stream end |

**Runtime implementation** (`asya_runtime.py`):
```python
def _stream_sse_response(self, message, user_func):
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")

    def on_fly(payload):
        data = json.dumps({"payload": payload})
        self.wfile.write(f"event: upstream\ndata: {data}\n\n".encode())

    def on_emit(frame):
        data = json.dumps(frame)
        self.wfile.write(f"event: downstream\ndata: {data}\n\n".encode())

    # Drive generator with ABI dispatch (FLY → on_fly, EMIT → on_emit)
    self._drive_generator(message, user_func, on_fly, on_emit)
    self.wfile.write(b"event: done\ndata: \n\n")
```

#### 9.5.2 Sidecar SSE Stream Parsing

The sidecar's runtime client (`internal/runtime/client.go`) parses the SSE stream
and dispatches each event type:

```
Sidecar receives SSE from runtime:
├── "downstream" → RuntimeResponse → queued to next actor via transport
├── "upstream"   → onUpstream callback → forwarded to gateway
├── "error"      → RuntimeError → message nacked, routed to x-sump
└── "done"       → stream complete, return all responses
```

The `onUpstream` callback is wired by the router to call
`progressReporter.ForwardPartial()`, which POSTs the raw FLY payload to the
gateway at `POST /mesh/{id}/partial`.

**FLY forwarding is fire-and-forget**: The sidecar does not wait for gateway
acknowledgment. If the gateway is unavailable, the event is logged and dropped.
This preserves the sidecar's non-blocking message processing guarantee.

#### 9.5.3 Gateway Partial Event Handling

The gateway's `HandleTaskPartial` receives the raw FLY payload and:

1. Wraps it in a `TaskUpdate` with `PartialPayload` field
2. Persists to `task_updates` table (column: `partial_payload JSONB`)
3. Broadcasts immediately to SSE subscribers

**A2A translation**: The gateway inspects the FLY dict's top-level key to
determine the SSE event type:

| FLY Dict Key | A2A SSE Event |
|-------------|---------------|
| `artifact_update` | `event: artifact_update` |
| `status_update` | `event: status_update` |
| `message` | `event: message` |
| (other) | `event: partial` (legacy/non-A2A) |

The gateway stamps `taskId` and `contextId` from the task record before
broadcasting.

#### 9.5.4 Full Pipeline Diagram

```
Actor Handler            Runtime              Sidecar              Gateway              Client
  |                       |                    |                    |                    |
  |-- yield "FLY",{...} ->|                    |                    |                    |
  |                       |-- event: upstream   |                    |                    |
  |                       |   data: {payload:  |                    |                    |
  |                       |          {...}} -->|                    |                    |
  |                       |                    |-- POST /mesh/{id}/ |                    |
  |                       |                    |   partial -------->|                    |
  |                       |                    |                    |-- SSE event ------->|
  |                       |                    |                    |  (artifact_update)  |
  |                       |                    |                    |                    |
  |-- yield payload ----->|                    |                    |                    |
  |                       |-- event: downstream|                    |                    |
  |                       |   data: {payload:  |                    |                    |
  |                       |    {...},route:{}} |                    |                    |
  |                       |                    |-- Route to next    |                    |
  |                       |                    |   actor queue      |                    |
  |                       |-- event: done ---->|                    |                    |
```

---

## 10. Pause/Resume and input_required

### 10.1 Actor-Initiated Pause

Pause is implemented via the x-pause crew actor and the `x-asya-pause` header
protocol (RFC 1ixy). The flow author places `x-pause` and `x-resume` in the
route where a pause point is needed:

```yaml
route: [analyzer, x-pause, x-resume, summarizer, x-sink]
```

**x-pause handler** (from RFC 1ixy section 3.2):

1. Verifies `x-resume` is next in route (prepends if missing)
2. Persists full envelope (payload + route + headers) to S3 via state proxy
3. Sets `x-asya-pause` header with pause metadata
4. Returns `None`

**x-asya-pause header schema** (from RFC 1ixy section 3.3):

```json
{
  "prompt": "Human-readable description of what input is needed",
  "fields": [
    {
      "name": "approved",
      "type": "boolean",
      "prompt": "Approve this analysis?",
      "payload_key": "/approved",
      "required": true
    },
    {
      "name": "notes",
      "type": "string",
      "prompt": "Any additional notes?",
      "payload_key": "/review/notes",
      "required": false,
      "default": null
    }
  ]
}
```

**Sidecar behavior** (from RFC 1ixy section 3.4): When sidecar receives
`x-asya-pause` header in runtime response:
1. Reports `phase: paused` + pause metadata to gateway via `POST /mesh/{id}/progress`
2. Acks the message (removes from queue)
3. Does NOT route to the next actor (x-resume)

### 10.2 Gateway State Transition

Gateway receives progress update with `phase: paused` (from RFC 1ixy section 3.5):

1. Update task status to `paused` (A2A: `INPUT_REQUIRED`)
2. Store pause metadata (prompt, fields) in `pause_metadata` JSONB column
3. Freeze timeout timer — save `remaining_timeout_sec`, stop timer
4. Broadcast `TaskStatusUpdateEvent` to SSE subscribers:

```json
{
  "taskId": "t-1",
  "contextId": "c-1",
  "status": {
    "state": "INPUT_REQUIRED",
    "message": {
      "role": "agent",
      "parts": [{"text": "Review this analysis before proceeding"}]
    }
  }
}
```

The `status.message` is constructed from the `prompt` field in pause metadata.

### 10.3 User-Initiated Resume

Client sends `SendMessage` with `task_id` referencing the paused task
(from RFC 1ixy section 4.1):

```json
{
  "method": "message/send",
  "params": {
    "message": {
      "message_id": "m-resume",
      "task_id": "t-1",
      "context_id": "c-1",
      "role": "user",
      "parts": [
        {"data": {"approved": true, "notes": "Looks good"}}
      ]
    }
  }
}
```

**Gateway resume flow** (from RFC 1ixy section 4.2):

1. Look up task by `task_id` — validate status is `paused`
2. Extract user input from A2A Message parts (same `messageToPayload` translation)
3. Create resume envelope:
   ```json
   {
     "id": "resume-uuid",
     "route": {"prev": [], "curr": "x-resume", "next": []},
     "headers": {
       "x-asya-resume-task": "t-1",
       "x-asya-a2a-task-id": "t-1",
       "x-asya-a2a-context-id": "c-1"
     },
     "payload": {"approved": true, "notes": "Looks good"}
   }
   ```
4. Queue to x-resume actor queue
5. Update task status to `running` (A2A: `WORKING`)
6. Thaw timeout timer — restart with saved `remaining_timeout_sec`
7. Return updated Task

**x-resume handler** (from RFC 1ixy section 4.3):

1. Reads `x-asya-resume-task` header to find persisted envelope
2. Loads persisted envelope from S3 via state proxy
3. Reads pause metadata to get field-to-payload-key mappings
4. Merges user input into restored payload at `payload_key` paths
5. If no field mappings (external pause), merges at payload root
6. Restores the route via ABI and continues the pipeline

### 10.4 History Accumulation During Pause/Resume

Each turn of a pause/resume conversation adds to `payload.a2a.task.history`:

1. **Initial send**: Gateway initializes `payload.a2a.task` with id, context_id,
   and appends user Message to `payload.a2a.task.history` before dispatching.
2. **Actor pause**: Actor (or x-pause) can append agent Message to history
   before pausing — e.g., `payload["a2a"]["task"]["history"].append({...})`
3. **Resume**: Gateway creates resume envelope with user's new Message in
   `payload.a2a.task.history`. x-resume loads original envelope from S3 and
   merges: appends resume history entries to restored history.

**x-resume history merge** (addition to RFC 1ixy):

```python
def resume_handler(payload):
    task_id = yield "GET", ".headers.x-asya-resume-task"
    persisted = load_message(task_id)  # From S3

    # Restore the original payload
    restored = persisted["payload"]

    # Append user's resume messages to A2A history
    resume_task = payload.get("a2a", {}).get("task", {})
    resume_history = resume_task.get("history", [])
    if resume_history:
        restored.setdefault("a2a", {}).setdefault("task", {}).setdefault("history", [])
        restored["a2a"]["task"]["history"].extend(resume_history)

    # Merge user input fields at configured payload_key paths
    pause_meta = persisted.get("_pause_metadata", {})
    fields = pause_meta.get("fields", [])
    for field in fields:
        name = field["name"]
        if name in payload:
            payload_key = field.get("payload_key", f"/{name}")
            set_at_path(restored, payload_key, payload[name])

    # If no field mappings, merge at root
    if not fields:
        restored.update({k: v for k, v in payload.items() if k != "a2a"})

    # Restore the route
    yield "SET", ".route.next", persisted["route"]["next"]

    yield restored
```

---

## 11. Internal Routes: Mesh Layer

### 11.1 Renamed Sidecar-Facing Routes

Per epic 1mx1, internal sidecar-facing routes move from `/tasks/` to `/mesh/`:

| Old Route | New Route | Purpose |
|-----------|-----------|---------|
| `POST /tasks/{id}/progress` | `POST /mesh/{id}/progress` | Sidecar progress |
| `POST /tasks/{id}/final` | `POST /mesh/{id}/final` | End actor final |
| `GET /tasks/{id}/active` | `GET /mesh/{id}/active` | Liveness check |
| `GET /tasks/{id}/stream` | `GET /mesh/{id}/stream` | SSE (internal) |
| `POST /tasks/{id}/partial` | `POST /mesh/{id}/partial` | FLY events |
| `POST /tasks` | `POST /mesh` | Fanout child |

### 11.2 Sidecar Changes for A2A

The sidecar operates identically regardless of whether a task was created via
MCP or A2A. Changes:

1. **Header stamping**: Gateway already stamps `x-asya-a2a-task-id` and
   `x-asya-a2a-context-id` in envelope headers. Sidecar reads `x-asya-a2a-task-id` for
   progress reporting (falls back to `envelope.id` if header missing — backward
   compatible).

2. **FLY forwarding**: FLY events from the runtime are forwarded to
   `POST /mesh/{id}/partial` as-is. The gateway handles the A2A translation.
   No sidecar change needed.

3. **Progress-based active check**: The sidecar's `POST /mesh/{id}/progress`
   report now doubles as an active check. If the gateway returns `410 Gone`
   instead of `200 OK`, the sidecar drops the envelope, persists it to x-sink
   queue, and does not route further. This handles cancellation (and any other
   terminal state transition) that happened while the envelope was in the queue.
   See Section 7.5 for the full cancellation flow.

4. **Artifact reporting**: x-sink's `POST /mesh/{id}/final` already sends the
   result. Gateway creates A2A Artifacts from this result. No sidecar change.

---

## 12. Authentication and Security

Authentication applies to A2A endpoints only. Internal `/mesh/*` routes and
MCP `/mcp` to be protected later, in future RFCs.

### Phase 1: No Auth (MVP)

Agent Card declares empty `securitySchemes`. Suitable for development and
internal deployments.

### Phase 2: API Key

```json
{
  "securitySchemes": {
    "apiKey": {
      "apiKeySecurityScheme": {
        "location": "header",
        "name": "X-API-Key"
      }
    }
  },
  "securityRequirements": [{"schemes": {"apiKey": []}}]
}
```

**Config**: `ASYA_A2A_API_KEY` env var. Middleware validates on all
`{base}/a2a/*` routes.

### Phase 3: Bearer Token (JWT)

```json
{
  "securitySchemes": {
    "bearer": {
      "httpAuthSecurityScheme": {
        "scheme": "bearer",
        "bearerFormat": "JWT"
      }
    }
  }
}
```

**Config**: `ASYA_A2A_JWT_ISSUER`, `ASYA_A2A_JWT_AUDIENCE`,
`ASYA_A2A_JWT_JWKS_URL`.

### Phase 4: OAuth2 (Enterprise)

Client Credentials flow for machine-to-machine agent authentication.

### Middleware Architecture

```go
// Applied to {base}/a2a/* routes only
func A2AAuthMiddleware(config AuthConfig) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            if !authenticate(r, config) {
                // Return A2A-formatted JSON-RPC error
                writeA2AError(w, -32005, "Authentication required")
                return
            }
            next.ServeHTTP(w, r)
        })
    }
}
```

---

## 13. Database Schema

### 13.1 Tasks Table Changes

```sql
-- Migration: add A2A columns
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS context_id TEXT;
CREATE INDEX IF NOT EXISTS idx_tasks_context_id ON tasks(context_id);

-- Add new status values
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
  CHECK (status IN (
    'pending', 'running', 'succeeded', 'failed', 'unknown',
    'paused', 'canceled', 'rejected', 'auth_required'
  ));
```

### 13.2 No Artifacts Table

Artifact content and references live in the envelope payload at
`payload.a2a.task.artifacts` and are persisted to S3 via x-sink. The gateway DB
does NOT store artifacts. `GetTask(includeArtifacts=true)` fetches from S3.

### 13.3 Push Notification Configs Table (Phase 4)

```sql
CREATE TABLE task_push_configs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    token TEXT,
    auth_scheme TEXT,
    auth_credentials TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_task_push_configs_task_id ON task_push_configs(task_id);
```

### 13.4 Tools Table

Replaces the former YAML-based `routes.yaml` ConfigMap. This is the full schema
(new table, not ALTER):

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
    a2a_examples     TEXT[] NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

| Column | Notes |
|--------|-------|
| `name` | Natural PK. Tool/skill identifier across MCP, A2A, CLI. |
| `actor` | Single entrypoint actor name. Gateway resolves to queue: `asya-{namespace}-{actor}`. |
| `parameters` | Full JSON Schema object. Passed through to MCP/A2A without interpretation. |
| `timeout_sec` | Per-tool timeout override. Null = gateway default. |
| `progress` | Whether to enable progress reporting for this tool. |
| `mcp_enabled` | Visible in MCP `tools/list`. Default true. |
| `a2a_enabled` | Visible in A2A Agent Card skills. Default false (explicit opt-in). |
| `a2a_tags` | A2A skill tags for discoverability. |
| `a2a_input_modes` | A2A skill input MIME types. |
| `a2a_output_modes` | A2A skill output MIME types. |
| `a2a_examples` | Example prompts for the A2A skill. |

---

## 14. Implementation Phases

### Phase 1: Core A2A (MVP)

Delivers: Agent Card, SendMessage, GetTask, SSE streaming. External A2A clients
can discover the gateway, send messages, and track results.

| Task | Description | Deps |
|------|-------------|------|
| Import `a2a-go` library | Add dependency, remove hand-rolled types | None |
| Implement `AsyaExecutor` | `Execute` + `Cancel` methods | a2a-go |
| Implement `A2AStoreAdapter` | Wrap PgStore for a2a-go TaskStore | a2a-go |
| Wire `a2asrv.NewHandler()` | Mount at configurable prefix | Executor, Store |
| Agent Card endpoint | `GET /.well-known/agent.json` from tools table | Tools table |
| Skill resolution | Extension-based + single-skill default | Tools table |
| Rename `/tasks/*` to `/mesh/*` | Epic 1mx1 (prereq for path clarity) | Sidecar update |
| DB migration: `context_id`, `a2a_enabled` on tools | Schema changes | None |
| State proxy URL extension | Return external URLs on write | State proxy |
| FLY A2A-native format | Update sidecar to pass FLY dicts to `/mesh/{id}/partial` | Sidecar |

**Estimated scope**: ~1500 lines of Go (new `internal/a2a/` package refactored
around a2a-go). ~200 lines sidecar changes (URL rename + FLY forwarding).

### Phase 2: Production Readiness

| Task | Description |
|------|-------------|
| API Key authentication | `ASYA_A2A_API_KEY` middleware on `{base}/a2a/*` |
| ListTasks with pagination | Internal TaskStore.List() + cursor pagination |
| CancelTask with sidecar support | Extend `/mesh/{id}/active` for canceled |
| Blocking mode | Hold connection for `configuration.blocking: true` |
| Runtime helpers | `fly_text()`, `fly_status()` in `asya_runtime.py` |

### Phase 3: Advanced Features

| Task | Description |
|------|-------------|
| Bearer/JWT authentication | `ASYA_A2A_JWT_*` env vars |
| Extended Agent Card | `GetExtendedAgentCard` with auth-gated details |
| LLM-based skill resolution | Intent classification for skill routing |
| GetTask history from S3 | Fetch `payload.a2a.task.history` from S3 for paused/completed |

### Phase 4: Extended Protocol

| Task | Description |
|------|-------------|
| Push notification CRUD | 4 methods + webhook delivery |
| OAuth2 authentication | Client Credentials flow |
| gRPC transport | `a2agrpc.NewHandler()` from a2a-go |

---

## 15. Testing Strategy

### 15.1 Unit Tests

| Component | What to Test | Location |
|-----------|-------------|----------|
| Message → payload translation | Part extraction, history construction, A2A nesting, single data part unwrap, text-only concat, mixed parts | `internal/a2a/translator_test.go` |
| State mapping | All 9 A2A states ↔ internal states, bidirectional | `internal/a2a/state_test.go` |
| Skill resolution | Extension-based, single-skill default, multi-skill rejection with guidance, task continuation | `internal/a2a/skill_resolver_test.go` |
| Agent Card generation | Skills filtering (a2a_enabled), capabilities flags, input/output modes, env var config | `internal/a2a/agent_card_test.go` |
| Store adapter | Internal ↔ A2A task translation, version tracking, list pagination | `internal/a2a/store_adapter_test.go` |
| Executor | New task envelope creation, resume detection for paused tasks, skill metadata in headers | `internal/a2a/executor_test.go` |
| Tool registry | CRUD operations, MCP/A2A filtering, in-memory refresh, concurrent access | `internal/toolstore/registry_test.go` |
| Partial event translation | FLY dict key → A2A SSE event type mapping | `internal/a2a/streaming_test.go` |
| Blocking mode | Timeout handling, terminal state detection, interrupted state detection | `internal/a2a/blocking_test.go` |

### 15.2 Component Tests (Docker Compose)

| Test | What to Verify |
|------|---------------|
| Agent Card served | `GET /.well-known/agent.json` returns valid A2A card with skills |
| SendMessage creates task | POST → task in DB → envelope in queue → correct actor routing |
| SendStreamingMessage SSE | POST → SSE stream with task/status_update/artifact_update events |
| GetTask format | A2A response with status, optional artifacts (from S3), omitted history for in-flight |
| GetTask paused with history | S3 fetch for paused task returns history from `payload.a2a.task.history` |
| ListTasks pagination | Cursor-based pagination, context_id filtering, status filtering |
| CancelTask | Cancel → status updated → sidecar stops routing (410 Gone) |
| Registration API | `POST /mesh/expose` upsert, `GET /mesh/expose` list |
| Registration refresh | POST new tool → Agent Card immediately reflects new skill |
| Auth middleware | 401 for unauthenticated, 200 for authenticated, no auth on `/mesh/*` |
| Blocking mode | `configuration.blocking: true` → response after completion |
| Error responses | JSON-RPC error codes for skill not found, task not found, invalid params |

### 15.3 Integration Tests (Docker Compose)

| Test | What to Verify |
|------|---------------|
| A2A end-to-end | SendMessage → actors → SSE result → GetTask returns artifacts |
| MCP + A2A parity | Same flow callable via both protocols, same result |
| Multi-turn conversation | Same context_id → grouped tasks in ListTasks |
| Pause/resume as input_required | Pause → INPUT_REQUIRED → resume with data → COMPLETED |
| FLY streaming pipeline | Actor FLY → runtime upstream SSE → sidecar → `/mesh/{id}/partial` → client SSE artifact_update |
| Multi-frame ordering | Multiple FLY events arrive in order at client SSE |
| Cancellation mid-flight | Cancel during actor processing → sidecar acks, no routing |
| Context_id propagation | context_id in headers, readable by actor via ABI GET |

### 15.4 E2E Tests (Kind cluster)

| Test | What to Verify |
|------|---------------|
| Agent Card with real AsyncActors | Skills match deployed flows via `POST /mesh/expose` |
| Full A2A flow with Crossplane | SendMessage → Crossplane-managed actors → result |
| Cross-namespace routing | Gateway routes to correct namespace queue |
| Auth enforcement | API Key required for A2A, not for MCP or `/mesh/*` |
| A2A SDK client interop | Official `a2a-go` client can discover, send, stream, cancel |
| Pause/resume with S3 | Full pause → S3 persist → resume → S3 load → continue |
| Concurrent tasks | Multiple tasks in same context, correct isolation |

---

## 16. Future Work

### AUTH_REQUIRED State

The A2A spec defines `AUTH_REQUIRED` as an interrupted state where the agent
needs the user to authenticate with an external service. This maps to a special
kind of pause:

- Actor signals `AUTH_REQUIRED` via ABI header
  (`yield "SET", ".headers.x-asya-auth-required", {...}`)
- Gateway transitions task to `auth_required` (A2A: `AUTH_REQUIRED`)
- Client authenticates externally and sends resume message with credentials
- Deferred to Phase 3+. When implemented, reuses the pause/resume mechanism
  with a different header and task state.

### State Proxy Integration for Cross-Task Context

For agentic flows that need to reference previous tasks in the same context:

- Actor reads/writes to `/state/context/{context_id}/` via state proxy (RFC 1dmf)
- Context ID is available in envelope headers
  (`yield "GET", ".headers.x-asya-a2a-context-id"`)
- This is actor-level business logic, not A2A protocol logic

### Multi-Tenancy

A2A's optional `tenant` parameter is ignored in this RFC. Asya's namespace-based
isolation provides multi-tenancy at the K8s level. If SaaS-style tenancy is
needed, `tenant` can be mapped to Asya namespaces.

### gRPC Transport

The a2a-go library provides `a2agrpc.NewHandler()` for gRPC transport. This can
be mounted alongside the JSON-RPC handler when gRPC support is needed.

### Agent Card Signing

A2A supports JWS signatures on the Agent Card for verification. Deferred until
security requirements demand it.

---

## Appendix A: A2A Proto → a2a-go Type Mapping

The `a2a-go` library provides Go types for all A2A proto messages. Key types used
by the gateway:

| Proto Message | Go Type | Used In |
|---------------|---------|---------|
| `Task` | `a2a.Task` | Store, responses |
| `TaskState` | `a2a.TaskState` | State machine |
| `TaskStatus` | `a2a.TaskStatus` | Events, responses |
| `Message` | `a2a.Message` | Input translation, history |
| `Part` (oneof) | `a2a.Part` with `PartContent` interface | Message/artifact parts |
| `Artifact` | `a2a.Artifact` | Task outputs |
| `AgentCard` | `a2a.AgentCard` | Discovery |
| `AgentSkill` | `a2a.AgentSkill` | Agent Card skills |
| `StreamResponse` | `a2a.StreamResponse` | SSE streaming |
| `TaskStatusUpdateEvent` | `a2a.TaskStatusUpdateEvent` | Status streaming |
| `TaskArtifactUpdateEvent` | `a2a.TaskArtifactUpdateEvent` | Artifact streaming |
| `SendMessageRequest` | `a2a.SendMessageRequest` | Inbound requests |
| `SendMessageConfig` | `a2a.SendMessageConfig` | Blocking, output modes |
| `PushNotificationConfig` | `a2a.PushNotificationConfig` | Webhooks |

## Appendix B: a2a-go Server Integration

The gateway wiring in `cmd/gateway/main.go`:

```go
// Create A2A components
executor := a2a.NewAsyaExecutor(queueClient, taskStore, skillRegistry, namespace)
a2aStore := a2a.NewStoreAdapter(taskStore)

// Create a2a-go handler
a2aHandler := a2asrv.NewHandler(executor,
    a2asrv.WithTaskStore(a2aStore),
    a2asrv.WithAgentCard(agentCardProvider),
)

// Mount with base prefix + fixed /a2a namespace
base := os.Getenv("ASYA_BASE_PREFIX") // "" or "/api/v1"
a2aPrefix := base + "/a2a"
jsonRPCHandler := a2asrv.NewJSONRPCHandler(a2aHandler)

mux.Handle(a2aPrefix+"/message:send", jsonRPCHandler)
mux.Handle(a2aPrefix+"/message:stream", jsonRPCHandler)
mux.Handle(a2aPrefix+"/tasks/", a2aHandler)  // REST routes
mux.Handle(a2aPrefix+"/extendedAgentCard", a2aHandler)

// MCP at {base}/mcp
mux.Handle(base+"/mcp", mcpHandler)
mux.Handle(base+"/mcp/tools/call", mcpToolCallHandler)

// Mesh management at {base}/mesh
mux.Handle(base+"/mesh/expose", meshExposeHandler)
mux.Handle(base+"/mesh/", meshHandler)  // sidecar routes

// Root-level (no prefix)
mux.HandleFunc("/.well-known/agent.json", a2aHandler.AgentCard)
mux.HandleFunc("/health", healthHandler)
```
