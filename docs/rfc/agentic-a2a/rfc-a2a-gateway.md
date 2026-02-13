# RFC: A2A Protocol Compliance for Asya Gateway

| Field       | Value                                                |
|-------------|------------------------------------------------------|
| **Status**  | Draft                                                |
| **Author**  | Artem Yushkovskiy                                    |
| **Created** | 2026-02-12                                           |
| **Epic**    | asya-7j1: Epic: A2A Protocol Compliance for Gateway  |
| **Related** | asya-n5u, asya-33qf, asya-j2vk, asya-vdc, asya-qrsp |
| **Spec**    | https://a2a-protocol.org/latest/specification/       |
| **Proto**   | https://github.com/google/A2A/blob/main/specification/a2a.proto |

## Table of Contents

- [1. Abstract](#1-abstract)
- [2. Motivation](#2-motivation)
- [3. Background](#3-background)
  - [3.1 Current Gateway Architecture](#31-current-gateway-architecture)
  - [3.2 A2A Protocol Overview](#32-a2a-protocol-overview)
  - [3.3 MCP vs A2A: Complementary Roles](#33-mcp-vs-a2a-complementary-roles)
- [4. Design Goals](#4-design-goals)
- [5. Architecture: Dual-Protocol Gateway](#5-architecture-dual-protocol-gateway)
  - [5.1 Endpoint Layout](#51-endpoint-layout)
  - [5.2 Request Flow](#52-request-flow)
  - [5.3 Selective Exposure Model](#53-selective-exposure-model)
- [6. Gap Analysis](#6-gap-analysis)
  - [6.1 Data Model Gaps](#61-data-model-gaps)
  - [6.2 API Endpoint Gaps](#62-api-endpoint-gaps)
  - [6.3 Sidecar Gaps](#63-sidecar-gaps)
  - [6.4 Infrastructure Gaps](#64-infrastructure-gaps)
  - [6.5 Beads Coverage Map](#65-beads-coverage-map)
- [7. Data Model Mapping](#7-data-model-mapping)
  - [7.1 Task State Mapping](#71-task-state-mapping)
  - [7.2 Message and Part Mapping](#72-message-and-part-mapping)
  - [7.3 Artifact Mapping](#73-artifact-mapping)
  - [7.4 Streaming Event Mapping](#74-streaming-event-mapping)
- [8. API Design](#8-api-design)
  - [8.1 Agent Card Discovery](#81-agent-card-discovery)
  - [8.2 POST /a2a/ --- Send Message](#82-post-a2a----send-message)
  - [8.3 POST /a2a/ (streaming) --- Send Streaming Message](#83-post-a2a-streaming----send-streaming-message)
  - [8.4 GET /a2a/tasks/{id} --- Get Task](#84-get-a2atasksid----get-task)
  - [8.5 GET /a2a/tasks --- List Tasks](#85-get-a2atasks----list-tasks)
  - [8.6 POST /a2a/tasks/{id}:cancel --- Cancel Task](#86-post-a2atasksidcancel----cancel-task)
  - [8.7 GET /a2a/tasks/{id}:subscribe --- Subscribe to Task](#87-get-a2atasksidsubscribe----subscribe-to-task)
  - [8.8 Push Notification CRUD](#88-push-notification-crud)
  - [8.9 Internal Endpoints (Sidecar-Facing)](#89-internal-endpoints-sidecar-facing)
- [9. Agent Card Generation from Flow Config](#9-agent-card-generation-from-flow-config)
  - [9.1 Unified Config YAML Schema](#91-unified-config-yaml-schema)
  - [9.2 ConfigMap Mount and Hot-Reload](#92-configmap-mount-and-hot-reload)
  - [9.3 Agent Card Construction](#93-agent-card-construction)
- [10. Sidecar Changes for A2A](#10-sidecar-changes-for-a2a)
  - [10.1 Streaming Event Forwarding](#101-streaming-event-forwarding)
  - [10.2 Artifact Reporting](#102-artifact-reporting)
  - [10.3 Task Cancellation Support](#103-task-cancellation-support)
- [11. Streaming Architecture](#11-streaming-architecture)
  - [11.1 A2A Streaming Response Format](#111-a2a-streaming-response-format)
  - [11.2 Mapping Sidecar Events to A2A Stream Events](#112-mapping-sidecar-events-to-a2a-stream-events)
  - [11.3 Multi-Frame Runtime Protocol Integration](#113-multi-frame-runtime-protocol-integration)
- [12. Authentication](#12-authentication)
- [13. Implementation Phases](#13-implementation-phases)
- [14. Testing Strategy](#14-testing-strategy)
- [15. Open Questions](#15-open-questions)

---

## 1. Abstract

This RFC specifies how to make asya-gateway compliant with the [A2A (Agent-to-Agent) protocol](https://a2a-protocol.org/latest/specification/), enabling external AI agents to discover and interact with Asya actor flows through a standardized interface.

The gateway exposes a **dual-protocol surface**: MCP (`/mcp`) for developer tool-calling and direct LLM integration, and A2A (`/a2a/`) for agent-to-agent interoperability. Both protocols share the same internal task store, queue infrastructure, and actor mesh. Users selectively expose flows as MCP tools, A2A skills, or both, via a single ConfigMap-based configuration.

The only Asya abstraction remains **AsyncActor**. Actors are grouped into flows via the `asya.sh/flow` label. Entrypoint and exitpoint actors are marked with `asya.sh/flow-role=entrypoint|exitpoint`. A single ConfigMap mounted into the gateway pod defines which flows are exposed as MCP tools and/or A2A skills, with `fsnotify`-based hot-reload.

## 2. Motivation

**Current state**: asya-gateway speaks MCP (JSON-RPC 2.0) and exposes a custom REST API for task management. External AI agents cannot discover or interact with Asya flows through any standard protocol.

**Target state**: External AI agents (Claude, GPT, Gemini, custom agents built with ADK/LangChain/CrewAI) can:

1. **Discover** Asya as an agent via `/.well-known/agent.json` (Agent Card)
2. **Invoke** exposed flows by sending A2A messages to `/a2a/`
3. **Stream** real-time progress and results via SSE
4. **Track** long-running tasks via `/a2a/tasks/{id}`
5. **Cancel** in-flight tasks

**Why A2A (not Agent Protocol)**: A2A's server-driven async model matches Asya's autonomous actor mesh architecture. Its protobuf-first schema provides code-generatable types. Its JSON-RPC 2.0 transport shares protocol infrastructure with MCP. AP's client-driven step model would require either faking steps or adding synchronization barriers that defeat Asya's pipeline autonomy. See detailed comparison in the `thoughts-a2a-gateway-pattern.md` design document.

## 3. Background

### 3.1 Current Gateway Architecture

The gateway serves as the synchronous HTTP interface to the async actor mesh:

```
                          +-----------------------------------+
                          |         asya-gateway              |
                          |                                   |
  Developer --- /mcp ---->|  MCP Server (mark3labs/mcp-go)    |
  Developer --- /tools/ ->|  REST Handler                     |
                          |         |                         |
                          |    +----v-----+  +----------+    |
                          |    | Registry |  |TaskStore |    |
                          |    | (tools)  |  |(PG/mem)  |    |
                          |    +----+-----+  +----------+    |
                          |         |                         |
                          |    +----v-----+                   |
                          |    |  Queue   |                   |
                          |    |(SQS/RMQ) |                   |
                          +----+----------+-------------------+
                                    |
                                    v
                          Actor Mesh (async processing)
```

**Current endpoints**:

| Endpoint | Method | Purpose | Consumer |
|---|---|---|---|
| `/mcp` | POST | MCP Streamable HTTP (JSON-RPC) | LLMs, developers |
| `/mcp/sse` | GET | MCP SSE (deprecated) | Legacy clients |
| `/tools/call` | POST | REST tool invocation | Developers |
| `/tasks/{id}` | GET | Task status | Clients |
| `/tasks/{id}/stream` | GET | SSE task updates | Clients |
| `/tasks/{id}/active` | GET | Task liveness check | Sidecars |
| `/tasks/{id}/progress` | POST | Progress reporting | Sidecars |
| `/tasks/{id}/final` | POST | Final status | End actors |
| `/tasks` | POST | Create fanout child | Sidecars |
| `/health` | GET | Health check | K8s probes |

**Current data model** (from `pkg/types/task.go`):

```go
type Task struct {
    ID, ParentID, Status, Route, Headers, Payload, Result, Error,
    TimeoutSec, Deadline, ProgressPercent, CurrentActorIdx,
    CurrentActorName, Message, ActorsCompleted, TotalActors,
    CreatedAt, UpdatedAt
}

type TaskStatus = "pending" | "running" | "succeeded" | "failed"
```

### 3.2 A2A Protocol Overview

A2A is a Google-initiated, Linux Foundation protocol for agent-to-agent interoperability. The normative schema source is `specification/a2a.proto`.

**Core concepts**:

- **AgentCard**: Published at `/.well-known/agent.json`. Declares capabilities, skills, authentication, supported interfaces.
- **Message**: Contains `role` (user/agent), `parts` (text/file/structured), `contextId` for grouping.
- **Task**: Server-created stateful work unit. States: `submitted -> working -> completed|failed|canceled|input_required|rejected`.
- **Artifact**: Named output produced during task execution. Contains `parts`.
- **StreamResponse**: SSE event containing `task | message | statusUpdate | artifactUpdate`.

**Protocol bindings**: JSON-RPC 2.0 over HTTP (primary), gRPC, HTTP REST.

**Service methods** (11 total):

| Method | Purpose |
|---|---|
| `SendMessage` | Send message, get Task or Message response |
| `SendStreamingMessage` | Same, with SSE stream response |
| `GetTask` | Retrieve task state |
| `ListTasks` | Paginated task list with filters |
| `CancelTask` | Request task cancellation |
| `SubscribeToTask` | SSE stream for existing task |
| `CreateTaskPushNotificationConfig` | Webhook setup |
| `GetTaskPushNotificationConfig` | Get webhook config |
| `ListTaskPushNotificationConfig` | List webhooks |
| `DeleteTaskPushNotificationConfig` | Remove webhook |
| `GetExtendedAgentCard` | Authenticated agent details |

### 3.3 MCP vs A2A: Complementary Roles

MCP and A2A serve fundamentally different consumers and remain on the gateway simultaneously:

| Aspect | MCP (`/mcp`) | A2A (`/a2a/`) |
|---|---|---|
| **Consumer** | LLMs doing tool-calling, developers | External AI agents, agent orchestrators |
| **Discovery** | Tool listing via `tools/list` | Agent Card at `/.well-known/agent.json` |
| **Invocation** | Explicit tool name + parameters | Message with intent, routed to skill |
| **Granularity** | Fine-grained (one tool = one route) | Coarse-grained (one skill = one flow) |
| **Response** | Task ID + URLs | Task object + streaming events |
| **Protocol** | JSON-RPC 2.0 | JSON-RPC 2.0 (same transport) |
| **Auth** | Typically none (internal) | Bearer, OAuth2, API Key |

**Example**: A `document-processing` flow with actors `[parser, analyzer, summarizer]` might be:
- **MCP tool**: `analyze_document` --- developer calls with explicit parameters
- **A2A skill**: `Document Analysis` --- external agent sends "Analyze this PDF for key themes"

Both create the same internal task and use the same queue/actor infrastructure.

## 4. Design Goals

1. **A2A spec compliance**: Implement the A2A HTTP/JSON-RPC binding faithfully, so any A2A SDK client can interact with Asya without custom code.

2. **Zero actor changes**: AsyncActor remains the only Asya abstraction. No new CRDs. Actors are unaware of whether they were invoked via MCP or A2A.

3. **Selective exposure**: Not every flow is A2A-exposed. Configuration controls which flows appear as A2A skills vs MCP tools vs both.

4. **Single ConfigMap**: One ConfigMap (`gateway-config`) mounted into the gateway pod defines all exposed tools and skills. Updated by `asya flow expose` CLI or directly by users.

5. **Hot-reload**: Gateway detects ConfigMap changes via `fsnotify` and re-registers tools/skills without restart.

6. **Streaming parity**: A2A streaming uses the same SSE infrastructure as MCP task streaming, with format adaptation.

7. **Incremental implementation**: Each phase delivers standalone value. Phase 1 (Agent Card + SendMessage) is sufficient for basic A2A interop.

## 5. Architecture: Dual-Protocol Gateway

### 5.1 Endpoint Layout

```
asya-gateway
|-- /.well-known/agent.json          # A2A Agent Card discovery
|-- /a2a/                            # A2A protocol surface
|   |-- POST   /a2a/                 # SendMessage / SendStreamingMessage (JSON-RPC dispatch)
|   |-- GET    /a2a/tasks            # ListTasks
|   |-- GET    /a2a/tasks/{id}       # GetTask
|   |-- POST   /a2a/tasks/{id}:cancel           # CancelTask
|   |-- GET    /a2a/tasks/{id}:subscribe         # SubscribeToTask (SSE)
|   `-- /a2a/tasks/{id}/pushNotificationConfigs  # Push CRUD (future)
|-- /mcp                             # MCP Streamable HTTP (unchanged)
|-- /mcp/sse                         # MCP SSE deprecated (unchanged)
|-- /tools/call                      # REST tool invocation (unchanged)
|-- /tasks/                          # Internal task API (sidecar-facing)
|   |-- GET    /tasks/{id}           # Task status (sidecar + legacy clients)
|   |-- GET    /tasks/{id}/stream    # SSE stream (legacy clients)
|   |-- GET    /tasks/{id}/active    # Task liveness (sidecars)
|   |-- POST   /tasks/{id}/progress  # Progress reporting (sidecars)
|   |-- POST   /tasks/{id}/final     # Final status (end actors)
|   |-- POST   /tasks/{id}/events    # Streaming events (sidecars, new)
|   `-- POST   /tasks                # Fanout child creation (sidecars)
`-- /health                          # Health check (unchanged)
```

**Design decision**: A2A endpoints live under `/a2a/` prefix rather than at root (`/messages`, `/tasks`). This avoids path collisions with the internal `/tasks/` API used by sidecars, and cleanly separates the external-facing A2A surface from internal infrastructure endpoints.

**Design decision**: `POST /a2a/` is a single JSON-RPC 2.0 endpoint that dispatches by method name (`message/send`, `message/stream`, `tasks/get`, etc.). This matches the A2A normative binding. The `/a2a/tasks/*` GET endpoints are convenience REST routes for simple queries that don't require JSON-RPC.

### 5.2 Request Flow

```
                   +----------------------------------------------------+
                   |                 asya-gateway                       |
                   |                                                    |
External Agent --->|  /.well-known/agent.json  ->  AgentCard (cached)   |
                   |                                                    |
External Agent --->|  POST /a2a/                                        |
                   |    |                                               |
                   |    +-- Parse JSON-RPC method                       |
                   |    +-- Parse A2A Message (parts -> payload)        |
                   |    +-- Resolve skill -> flow -> entrypoint actor   |
                   |    +-- Create Task (A2A state machine)             |
                   |    +-- Enqueue to entrypoint actor                 |
                   |    `-- Return Task (or stream StreamResponse)      |
                   |                                                    |
Developer -------->|  POST /mcp  (tools/call)                           |
                   |    |                                               |
                   |    +-- Parse MCP CallToolRequest                   |
                   |    +-- Resolve tool -> route                       |
                   |    +-- Create Task (same TaskStore)                |
                   |    +-- Enqueue to first actor                      |
                   |    `-- Return MCP CallToolResult                   |
                   |                                                    |
                   |  +----------+    +----------+    +-----------+    |
                   |  |  A2A     |    | Shared   |    |  MCP      |    |
                   |  | Registry |--->|TaskStore |<---|  Registry |    |
                   |  | (skills) |    | (PG)     |    | (tools)   |    |
                   |  +----------+    +----+-----+    +-----------+    |
                   |                       |                            |
                   |                  +----v-----+                      |
                   |                  |  Queue   |                      |
                   |                  |(SQS/RMQ) |                      |
                   +------------------+----------+----------------------+
                                          |
                                          v
                                    Actor Mesh
```

### 5.3 Selective Exposure Model

Flows and individual actor routes can be exposed through different protocol surfaces:

| Exposure | Config Key | Visible In | Use Case |
|---|---|---|---|
| MCP only | `mcp: true, a2a: false` | `/mcp` tools/list | Internal dev tools, pipeline stages |
| A2A only | `mcp: false, a2a: true` | Agent Card skills | Agent-facing capabilities |
| Both | `mcp: true, a2a: true` | Both | Public APIs accessible by both LLMs and agents |
| Neither | Not in config | Hidden | Internal-only flows, system actors |

## 6. Gap Analysis

### 6.1 Data Model Gaps

| A2A Concept | Asya Today | Gap | Severity |
|---|---|---|---|
| `Task.id` | `Task.ID` (UUID) | ✅ None | --- |
| `Task.context_id` | Not implemented | ❌ No conversation grouping | Medium |
| `Task.status.state` (8 states) | `TaskStatus` (4 states) | ❌ Missing: `submitted`, `input_required`, `canceled`, `rejected` | High |
| `Task.status.message` | `Task.Message` | ✅ Exists | --- |
| `Task.status.timestamp` | `Task.UpdatedAt` | ✅ Exists | --- |
| `Task.history` (Message[]) | Not tracked | ❌ No conversation history | Medium |
| `Task.artifacts` | S3 URI in metadata | ❌ No structured artifact model | Medium |
| `Task.metadata` | `Route.Metadata` | 🟡 Partial (route-level only) | Low |
| `Message.role` | Not applicable | ❌ No role concept | Low |
| `Message.parts` | `Task.Payload` (flat JSON) | ❌ No multi-part model | Medium |
| `Part` (text/file/structured) | Payload is always structured JSON | 🟡 Partial | Low |
| `Artifact` (id, name, parts) | Happy-end S3 URI | ❌ No artifact registry | Medium |
| `AgentCard` | Not implemented | ❌ No discovery | High |
| `AgentSkill` | Tool config YAML | 🟡 Similar but different schema | Medium |
| `StreamResponse` | SSE `TaskUpdate` events | 🟡 Different event format | Medium |
| `TaskStatusUpdateEvent` | Progress/Final updates | 🟡 Similar but different schema | Low |
| `TaskArtifactUpdateEvent` | Not implemented | ❌ No artifact streaming | Medium |
| `PushNotificationConfig` | Not implemented | ❌ No webhooks | Low |
| `SecurityScheme` | Not implemented | ❌ No auth | High |
| `context_id` grouping | Not implemented | ❌ No multi-turn | Medium |

### 6.2 API Endpoint Gaps

| A2A Endpoint | Asya Today | Gap | Bead |
|---|---|---|---|
| `/.well-known/agent.json` | ❌ Not implemented | Full implementation needed | asya-4c1 |
| `POST /a2a/` (SendMessage) | ❌ Not implemented (closest: `/tools/call`) | New handler, message parsing, skill resolution | asya-u76 |
| `POST /a2a/` (streaming) | ❌ Not implemented (closest: `/tasks/{id}/stream`) | SSE response on POST, StreamResponse format | asya-ey0 |
| `GET /a2a/tasks/{id}` | 🟡 `/tasks/{id}` exists but wrong format | A2A response format wrapper | asya-2n8 |
| `GET /a2a/tasks` | ❌ Not implemented | List with pagination, filtering | asya-ahb |
| `POST /a2a/tasks/{id}:cancel` | ❌ Not implemented | Cancellation signaling to mesh | asya-78f |
| `GET /a2a/tasks/{id}:subscribe` | 🟡 `/tasks/{id}/stream` exists but wrong format | A2A StreamResponse format | asya-z80 |
| Push notification CRUD | ❌ Not implemented | Webhook registration + delivery | asya-ly9 |
| `GetExtendedAgentCard` | ❌ Not implemented | Auth-gated agent details | --- |

### 6.3 Sidecar Gaps

| Requirement | Asya Today | Gap | Bead |
|---|---|---|---|
| Report streaming events to gateway | ❌ Only progress + final | New `POST /tasks/{id}/events` endpoint | asya-n5mc |
| Multi-frame runtime protocol | ❌ Single-frame only | Stream/result frame types | asya-qrsp |
| Artifact metadata in final report | 🟡 S3 URI in metadata | Structured artifact fields | --- |
| Task cancellation check | 🟡 `/tasks/{id}/active` exists | Respect cancellation signal | asya-78f |
| A2A terminology in logs/metrics | 🟡 Uses "task" already | Minor naming alignment | asya-57s |

### 6.4 Infrastructure Gaps

| Requirement | Asya Today | Gap | Bead |
|---|---|---|---|
| `fsnotify` config hot-reload | ❌ Config loaded once at startup | File watcher + registry rebuild | asya-j2vk |
| Singleton ConfigMap pattern | ❌ Static YAML file | ConfigMap mount + CLI tooling | asya-33qf |
| Authentication middleware | ❌ No auth | Bearer, API Key, OAuth2 | asya-wir |
| `context_id` in TaskStore | ❌ Not tracked | Schema migration, query support | asya-r52 |
| Error response format (A2A) | ❌ Plain HTTP errors | JSON-RPC error objects | asya-71m |

### 6.5 Beads Coverage Map

Existing beads under the A2A epic (asya-7j1) and their alignment to this RFC:

| Bead | Title | RFC Section | Status | Phase |
|---|---|---|---|---|
| asya-uic | Rename envelope to task throughout gateway | Prerequisite | In Progress | 0 |
| asya-4c1 | Agent Card discovery endpoint | 8.1, 9.3 | Open | 1 |
| asya-u76 | POST /messages endpoint | 8.2 | Open | 1 |
| asya-ey0 | POST /messages:stream endpoint | 8.3, 11 | Open | 1 |
| asya-2n8 | GET /tasks/{id} endpoint | 8.4 | Open | 1 |
| asya-z80 | GET /tasks/{id}:subscribe SSE | 8.7, 11 | Open | 1 |
| asya-71m | A2A error response format | 8.2 | Open | 1 |
| asya-j2vk | fsnotify config hot-reload | 9.2 | Open | 1 |
| asya-r52 | context_id support | 7.2 | Open | 2 |
| asya-57s | Sidecar A2A terminology | 10 | Open | 2 |
| asya-ahb | GET /tasks (list) | 8.5 | Open | 2 |
| asya-78f | POST /tasks/{id}:cancel | 8.6, 10.3 | Open | 2 |
| asya-wir | Authentication middleware | 12 | Open | 2 |
| asya-r7d | input_required state | 7.1 | Open | 3 |
| asya-0wr | AG-UI event streaming | --- | Open | 3 |
| asya-qyu | Map events to AG-UI types | --- | Open | 3 |
| asya-ly9 | Push notification endpoints | 8.8 | Open | 4 |
| asya-ybm | gRPC transport | --- | Open | 4 |
| asya-53w | A2UI payload support | --- | Open | 4 |

**New beads needed** (not yet tracked):

| Title | RFC Section | Phase |
|---|---|---|
| Add `a2a` section to gateway config schema | 9.1 | 1 |
| Implement A2A skill registry (alongside MCP tool registry) | 5.2 | 1 |
| Add artifact model to TaskStore | 7.3 | 2 |
| POST /tasks/{id}/events for sidecar streaming | 8.9, 10.1 | 2 |
| PgStore: add context_id column + migration | 7.2 | 2 |
| PgStore: add artifacts table + migration | 7.3 | 2 |

## 7. Data Model Mapping

### 7.1 Task State Mapping

A2A defines 8 task states. Asya currently has 4. The mapping:

```
A2A TaskState              Asya TaskStatus       Direction     Notes
---------------------------------------------------------------------------
SUBMITTED                  pending               A2A -> Asya   Task created, not yet queued
WORKING                    running               A2A -> Asya   Actor(s) processing
COMPLETED                  succeeded             A2A -> Asya   All actors finished successfully
FAILED                     failed                A2A -> Asya   Error in any actor
CANCELED                   (new: canceled)        A2A -> Asya   Client requested cancellation
INPUT_REQUIRED             (new: input_required)  A2A -> Asya   Actor needs human input
REJECTED                   (new: rejected)        A2A -> Asya   Gateway refused the request
AUTH_REQUIRED              (not mapped)           ---           Handled at HTTP layer, not task state
```

**Implementation**: Extend `TaskStatus` in `pkg/types/task.go`:

```go
const (
    TaskStatusPending       TaskStatus = "pending"        // A2A: SUBMITTED
    TaskStatusRunning       TaskStatus = "running"        // A2A: WORKING
    TaskStatusSucceeded     TaskStatus = "succeeded"      // A2A: COMPLETED
    TaskStatusFailed        TaskStatus = "failed"         // A2A: FAILED
    TaskStatusCanceled      TaskStatus = "canceled"       // A2A: CANCELED (new)
    TaskStatusInputRequired TaskStatus = "input_required" // A2A: INPUT_REQUIRED (new)
    TaskStatusRejected      TaskStatus = "rejected"       // A2A: REJECTED (new)
)
```

**`input_required` semantics**: When an actor in the pipeline needs user input (e.g., confirmation, clarification), it can return a special response that causes the sidecar to set task state to `input_required`. The task pauses until a follow-up message is sent with the same `context_id` + `task_id`. This is Phase 3 functionality (asya-r7d).

**`canceled` semantics**: When a client calls `CancelTask`, the gateway:
1. Sets task status to `canceled` in TaskStore
2. Sidecars polling `/tasks/{id}/active` receive `410 Gone`
3. In-flight actors complete their current processing but the sidecar does not route to the next actor
4. The message is acked (not nacked) to prevent DLQ pollution

**`rejected` semantics**: Gateway returns `rejected` when:
- The requested skill does not exist
- Input validation fails
- Rate limiting is applied
- Authentication/authorization fails at skill level

### 7.2 Message and Part Mapping

A2A `Message` is richer than Asya's flat payload. The gateway translates between them:

**Inbound (A2A Message -> Asya payload)**:

```
A2A Message {                         Asya Task {
  role: "user",                         // not stored (always "user" for inbound)
  parts: [                              payload: {
    {text: "Analyze this"},               "_a2a_text": "Analyze this",
    {data: {key: "val"}},                 "key": "val",
    {url: "s3://bucket/file.pdf",         "_a2a_files": [
     media_type: "application/pdf"}         {"url": "s3://bucket/file.pdf",
  ],                                         "media_type": "application/pdf"}
  context_id: "conv-123",                ],
  task_id: "task-456"                   },
}                                       context_id: "conv-123"
                                      }
```

**Payload construction rules**:
1. If the message has exactly one `structured` part (data) and no other parts: unwrap it as the payload directly (most common case --- structured API calls)
2. If the message has text parts: merge into `_a2a_text` field
3. If the message has file parts: collect into `_a2a_files` array
4. If mixed: combine all into a single payload object with reserved `_a2a_*` keys
5. If the message has `task_id`: this is a multi-turn continuation (see context_id handling)

**Outbound (Asya result -> A2A Message)**:

```
Asya Task {                           A2A Task {
  result: {score: 0.87, ...},          artifacts: [{
  // S3 URI from happy-end               artifact_id: "result-1",
  metadata: {                             parts: [{
    s3_uri: "s3://b/results/x.json"         data: {score: 0.87, ...}
  }                                       }]
}                                       }],
                                        status: {state: COMPLETED}
                                      }
```

**`context_id` handling**:
- First message in a conversation: gateway generates `context_id` (UUID)
- Subsequent messages with same `context_id`: grouped in task history
- `context_id` stored as a new column in the `tasks` table
- `ListTasks` can filter by `context_id`

### 7.3 Artifact Mapping

A2A artifacts are structured outputs. Asya currently stores results as opaque JSON in `Task.Result` and files in S3 via happy-end.

**Mapping strategy**:

| Asya Source | A2A Artifact |
|---|---|
| `Task.Result` (JSON) | Artifact with `structured` part |
| S3 URI from happy-end metadata | Artifact with `file` part (url + media_type) |
| Streaming events (future) | `TaskArtifactUpdateEvent` with `append=true` |

**New artifact table** (PostgreSQL migration):

```sql
CREATE TABLE task_artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    name TEXT,
    description TEXT,
    parts JSONB NOT NULL,          -- Array of A2A Part objects
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_task_artifacts_task_id ON task_artifacts(task_id);
```

**In-memory store**: Add `artifacts map[string][]Artifact` to the in-memory `Store`.

### 7.4 Streaming Event Mapping

A2A defines `StreamResponse` as a `oneof` with 4 event types. Map existing Asya events:

| Asya Event | A2A StreamResponse Type | When |
|---|---|---|
| Task created | `StreamResponse.task` | First event after SendStreamingMessage |
| Progress: "received" | `StreamResponse.status_update` | Sidecar received message from queue |
| Progress: "processing" | `StreamResponse.status_update` | Sidecar sent to runtime |
| Progress: "completed" | `StreamResponse.status_update` | Runtime returned result |
| Final: succeeded | `StreamResponse.status_update` (COMPLETED) | Happy-end reported |
| Final: failed | `StreamResponse.status_update` (FAILED) | Error-end reported |
| Result available | `StreamResponse.artifact_update` | Result stored as artifact |
| Streaming frame (future) | `StreamResponse.artifact_update` (append) | Multi-frame runtime response |

**SSE wire format** (A2A HTTP binding):

```
event: task
data: {"id":"task-123","contextId":"ctx-456","status":{"state":"submitted","timestamp":"..."}}

event: status_update
data: {"taskId":"task-123","contextId":"ctx-456","status":{"state":"working","message":{"role":"agent","parts":[{"text":"Processing at actor 'analyzer' (1/3)"}]},"timestamp":"..."}}

event: artifact_update
data: {"taskId":"task-123","contextId":"ctx-456","artifact":{"artifactId":"result-1","parts":[{"data":{"score":0.87}}]},"lastChunk":true}

event: status_update
data: {"taskId":"task-123","contextId":"ctx-456","status":{"state":"completed","timestamp":"..."}}
```

## 8. API Design

All A2A endpoints live under the `/a2a/` prefix. Field names use `camelCase` per A2A JSON convention (protobuf JSON mapping).

### 8.1 Agent Card Discovery

**Endpoint**: `GET /.well-known/agent.json`

Returns the A2A Agent Card describing the gateway's capabilities and exposed skills. Generated dynamically from the loaded config.

**Response**:

```json
{
  "name": "Asya Gateway",
  "description": "AI Actor Mesh for distributed workloads",
  "version": "0.1.0",
  "provider": {
    "organization": "Asya",
    "url": "https://asya.sh"
  },
  "supportedInterfaces": [
    {
      "url": "https://gateway.example.com/a2a/",
      "protocolBinding": "jsonrpc-over-http",
      "protocolVersion": "0.2.6"
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
      "outputModes": ["application/json"]
    }
  ],
  "securitySchemes": {},
  "securityRequirements": []
}
```

**Implementation notes**:
- Skills are generated from config entries with `a2a: true` (see Section 9.1)
- `supportedInterfaces[0].url` is configured via `ASYA_GATEWAY_PUBLIC_URL` env var
- `capabilities.streaming` is always `true` (SSE support)
- `capabilities.pushNotifications` set to `true` once Phase 4 is implemented

### 8.2 POST /a2a/ --- Send Message

**A2A method**: `message/send`

Accepts an A2A `Message`, resolves the target skill/flow, creates a task, enqueues the message to the entrypoint actor, and returns the created `Task`.

**Request** (JSON-RPC 2.0):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "msg-001",
      "role": "user",
      "parts": [
        {"text": "Analyze this quarterly report"},
        {"data": {"format": "pdf", "depth": "detailed"}}
      ],
      "contextId": "ctx-abc",
      "extensions": ["asya.sh/skill-hint"]
    },
    "configuration": {
      "acceptedOutputModes": ["application/json"],
      "blocking": false
    },
    "metadata": {
      "asya.sh/skill": "analyze-document"
    }
  }
}
```

**Skill resolution strategy** (in order):

1. **Explicit skill hint**: `metadata["asya.sh/skill"]` names the skill directly
2. **Task continuation**: If `message.taskId` is set, route to the existing task's flow
3. **Skill matching** (future): Match message text against skill descriptions

**Response** (non-blocking):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "task": {
      "id": "task-789",
      "contextId": "ctx-abc",
      "status": {
        "state": "submitted",
        "timestamp": "2026-02-12T10:00:00Z"
      },
      "artifacts": []
    }
  }
}
```

**Response** (blocking mode, `configuration.blocking: true`):

Gateway holds the HTTP connection open until the task reaches a terminal or interrupted state, then returns the final task:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "task": {
      "id": "task-789",
      "contextId": "ctx-abc",
      "status": {
        "state": "completed",
        "timestamp": "2026-02-12T10:00:30Z"
      },
      "artifacts": [{
        "artifactId": "result-1",
        "parts": [{"data": {"themes": ["revenue growth", "market expansion"]}}]
      }]
    }
  }
}
```

**Error responses** (A2A JSON-RPC errors):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32001,
    "message": "Skill not found: unknown-skill"
  }
}
```

| Error Code | Meaning |
|---|---|
| -32600 | Invalid Request (malformed JSON-RPC) |
| -32601 | Method Not Found |
| -32602 | Invalid Params (missing required fields) |
| -32001 | Skill Not Found |
| -32002 | Task Not Found |
| -32003 | Task Cancelled |
| -32004 | Push Notification Not Supported |
| -32005 | Authentication Required |

### 8.3 POST /a2a/ (streaming) --- Send Streaming Message

**A2A method**: `message/stream`

Same endpoint as SendMessage (`POST /a2a/`), dispatched by JSON-RPC method name. Returns an SSE stream instead of a single JSON response.

**Request**: Same as SendMessage, with `method: "message/stream"`.

**Response**: `Content-Type: text/event-stream`

```
event: task
data: {"id":"task-789","contextId":"ctx-abc","status":{"state":"submitted","timestamp":"..."}}

event: status_update
data: {"taskId":"task-789","contextId":"ctx-abc","status":{"state":"working","message":{"role":"agent","parts":[{"text":"Processing at 'parser' (1/3)"}]},"timestamp":"..."}}

event: status_update
data: {"taskId":"task-789","contextId":"ctx-abc","status":{"state":"working","message":{"role":"agent","parts":[{"text":"Processing at 'analyzer' (2/3)"}]},"timestamp":"..."}}

event: artifact_update
data: {"taskId":"task-789","contextId":"ctx-abc","artifact":{"artifactId":"result-1","name":"Analysis Result","parts":[{"data":{"themes":["revenue"],"sentiment":"positive"}}]},"lastChunk":true}

event: status_update
data: {"taskId":"task-789","contextId":"ctx-abc","status":{"state":"completed","timestamp":"..."}}
```

**Implementation**: The gateway:
1. Creates the task (same as SendMessage)
2. Subscribes to TaskStore updates (same mechanism as existing SSE)
3. Translates `TaskUpdate` events into A2A `StreamResponse` format
4. Sends initial `task` event
5. Sends `status_update` events for each progress update
6. Sends `artifact_update` when result is available
7. Sends final `status_update` with terminal state
8. Closes SSE connection

### 8.4 GET /a2a/tasks/{id} --- Get Task

**A2A method**: `tasks/get`

**Request**: `GET /a2a/tasks/task-789?historyLength=5`

**Response**:

```json
{
  "id": "task-789",
  "contextId": "ctx-abc",
  "status": {
    "state": "working",
    "message": {
      "role": "agent",
      "parts": [{"text": "Processing at 'analyzer' (2/3)"}]
    },
    "timestamp": "2026-02-12T10:00:15Z"
  },
  "artifacts": [],
  "history": [
    {
      "messageId": "msg-001",
      "role": "user",
      "parts": [{"text": "Analyze this quarterly report"}],
      "contextId": "ctx-abc"
    }
  ]
}
```

**Implementation**: Wraps existing `TaskStore.Get()` with A2A response format. The `historyLength` parameter controls how many messages to include in `history` (0 = none, unset = default 10).

### 8.5 GET /a2a/tasks --- List Tasks

**A2A method**: `tasks/list`

**Request**: `GET /a2a/tasks?contextId=ctx-abc&status=working&pageSize=10&pageToken=xxx`

**Query parameters**:

| Param | Type | Description |
|---|---|---|
| `contextId` | string | Filter by conversation |
| `status` | TaskState | Filter by state |
| `pageSize` | int | Items per page (default 10, max 100) |
| `pageToken` | string | Cursor for next page |
| `historyLength` | int | Messages per task (default 0) |
| `includeArtifacts` | bool | Include artifacts (default false) |

**Response**:

```json
{
  "tasks": [],
  "nextPageToken": "eyJvZmZzZXQiOjEwfQ==",
  "pageSize": 10,
  "totalSize": 42
}
```

**Implementation**: Requires new `TaskStore.List()` method with cursor-based pagination. Cursor is a base64-encoded offset. The PostgreSQL store uses `LIMIT/OFFSET` with optional `WHERE` clauses for `context_id` and `status` filters.

### 8.6 POST /a2a/tasks/{id}:cancel --- Cancel Task

**A2A method**: `tasks/cancel`

**Request**: `POST /a2a/tasks/task-789:cancel`

**Response**: Returns the updated Task with `status.state: "canceled"`.

**Cancellation flow**:

```
Client                     Gateway              Sidecar             Actor Mesh
  |                          |                     |                    |
  |-- POST :cancel --------->|                     |                    |
  |                          |-- Set canceled ----->| TaskStore          |
  |                          |                     |                    |
  |<-- Task{canceled} -------|                     |                    |
  |                          |                     |                    |
  |                          |     (next poll)     |                    |
  |                          |<-- GET /active -----|                    |
  |                          |--- 410 Gone ------->|                    |
  |                          |                     |-- Ack + stop ----->|
```

The sidecar's existing `/tasks/{id}/active` endpoint already returns `410 Gone` for completed/failed tasks. Extending it to also return `410` for `canceled` requires minimal change.

### 8.7 GET /a2a/tasks/{id}:subscribe --- Subscribe to Task

**A2A method**: `tasks/subscribe`

SSE stream for an existing task. Identical to SendStreamingMessage but for tasks that were created earlier (via SendMessage or even MCP).

**Request**: `GET /a2a/tasks/task-789:subscribe`

**Response**: SSE stream of `StreamResponse` events (same format as Section 8.3).

**Implementation**: Wraps existing `HandleTaskStream` with A2A event format translation. Includes historical replay (existing `GetUpdates`).

### 8.8 Push Notification CRUD

**Phase 4** --- deferred. These endpoints allow clients to register webhooks for async task updates instead of holding SSE connections.

| Endpoint | Method | Purpose |
|---|---|---|
| `/a2a/tasks/{id}/pushNotificationConfigs` | POST | Register webhook |
| `/a2a/tasks/{id}/pushNotificationConfigs/{configId}` | GET | Get webhook config |
| `/a2a/tasks/{id}/pushNotificationConfigs` | GET | List webhooks |
| `/a2a/tasks/{id}/pushNotificationConfigs/{configId}` | DELETE | Remove webhook |

**Webhook delivery**: When a task update occurs, gateway POSTs a `StreamResponse` to the registered URL with configured authentication headers.

### 8.9 Internal Endpoints (Sidecar-Facing)

These endpoints are NOT part of the A2A spec. They are internal infrastructure endpoints used by sidecars to report status to the gateway.

**Existing** (unchanged):

| Endpoint | Purpose |
|---|---|
| `POST /tasks/{id}/progress` | Sidecar reports actor progress |
| `POST /tasks/{id}/final` | End actors report completion |
| `GET /tasks/{id}/active` | Sidecar checks task liveness |
| `POST /tasks` | Sidecar creates fanout children |

**New** (Phase 2):

| Endpoint | Purpose |
|---|---|
| `POST /tasks/{id}/events` | Sidecar forwards streaming frames from runtime |

The `/tasks/{id}/events` endpoint accepts streaming frames from sidecars (multi-frame protocol, asya-qrsp) and:
1. Creates `TaskArtifactUpdateEvent` entries
2. Broadcasts to SSE subscribers
3. Stores in event history for replay

## 9. Agent Card Generation from Flow Config

### 9.1 Unified Config YAML Schema

The existing gateway config schema (in `internal/config/routes.go`) is extended with A2A-specific fields. A single ConfigMap defines both MCP tools and A2A skills:

```yaml
# ConfigMap: gateway-config
# Mounted at: /etc/asya-gateway/config/
# Watched by: fsnotify for hot-reload

# Gateway-level A2A configuration
a2a:
  name: "Asya Gateway"
  description: "AI Actor Mesh for distributed workloads"
  version: "0.1.0"
  provider:
    organization: "Asya"
    url: "https://asya.sh"

defaults:
  progress: true
  timeout: 300

routes:
  document-pipeline: [parser, analyzer, summarizer]
  payment-pipeline: [validator, processor, notifier]

# Each tool/skill entry
tools:
  # Exposed as BOTH MCP tool and A2A skill
  - name: analyze_document
    description: "Analyze documents for key themes and sentiment"
    mcp: true                       # Expose as MCP tool (default: true)
    a2a:                            # Expose as A2A skill
      enabled: true
      tags: [analysis, nlp, documents]
      input_modes: [application/json, application/pdf]
      output_modes: [application/json]
      examples:
        - "Analyze this quarterly report for key themes"
        - "What is the sentiment of this document?"
    parameters:
      text:
        type: string
        description: "Text content to analyze"
        required: true
      format:
        type: string
        options: [brief, detailed]
        default: brief
    route: document-pipeline
    timeout: 120

  # Exposed as MCP tool ONLY (internal pipeline stage)
  - name: validate_payment
    description: "Validate payment details"
    mcp: true
    a2a: false                      # Not exposed to external agents
    parameters:
      amount: {type: number, required: true}
      currency: {type: string, required: true}
    route: [payment-validator]

  # Exposed as A2A skill ONLY (agent-facing, not in MCP tools/list)
  - name: process_refund
    description: "Process a customer refund"
    mcp: false
    a2a:
      enabled: true
      tags: [payments, refunds]
    parameters:
      order_id: {type: string, required: true}
      reason: {type: string}
    route: payment-pipeline
```

**Schema extension** (Go struct changes in `config/routes.go`):

```go
// A2AConfig represents gateway-level A2A configuration
type A2AConfig struct {
    Name        string      `yaml:"name"`
    Description string      `yaml:"description"`
    Version     string      `yaml:"version"`
    Provider    A2AProvider `yaml:"provider,omitempty"`
}

type A2AProvider struct {
    Organization string `yaml:"organization"`
    URL          string `yaml:"url"`
}

// A2ASkillConfig represents per-tool A2A exposure settings
type A2ASkillConfig struct {
    Enabled     bool     `yaml:"enabled"`
    Tags        []string `yaml:"tags,omitempty"`
    InputModes  []string `yaml:"input_modes,omitempty"`
    OutputModes []string `yaml:"output_modes,omitempty"`
    Examples    []string `yaml:"examples,omitempty"`
}

// Updated Tool struct
type Tool struct {
    Name        string               `yaml:"name"`
    Description string               `yaml:"description"`
    Parameters  map[string]Parameter `yaml:"parameters"`
    Route       RouteSpec            `yaml:"route"`
    Progress    *bool                `yaml:"progress,omitempty"`
    Timeout     *int                 `yaml:"timeout,omitempty"`
    Metadata    map[string]string    `yaml:"metadata,omitempty"`
    MCP         *bool                `yaml:"mcp,omitempty"`  // default: true
    A2A         interface{}          `yaml:"a2a,omitempty"`  // bool or A2ASkillConfig
}

// Updated Config struct
type Config struct {
    A2A      *A2AConfig          `yaml:"a2a,omitempty"`
    Tools    []Tool              `yaml:"tools"`
    Routes   map[string][]string `yaml:"routes,omitempty"`
    Defaults *ToolDefaults       `yaml:"defaults,omitempty"`
}
```

**`a2a` field semantics**: The `a2a` field on a tool can be:
- `false` or omitted: not exposed as A2A skill (default)
- `true`: exposed with auto-generated tags from tool name
- `{enabled: true, tags: [...], ...}`: exposed with explicit configuration

**`mcp` field semantics**: The `mcp` field on a tool can be:
- `true` or omitted: exposed as MCP tool (default, backward compatible)
- `false`: not exposed in MCP tools/list

### 9.2 ConfigMap Mount and Hot-Reload

**Deployment pattern** (Helm chart values):

```yaml
# deploy/helm-charts/asya-gateway/values.yaml
config:
  configMapName: "gateway-config"
  mountPath: "/etc/asya-gateway/config"
```

**Helm template** (gateway deployment):

```yaml
volumes:
  - name: gateway-config
    configMap:
      name: {{ .Values.config.configMapName }}
containers:
  - name: gateway
    env:
      - name: ASYA_CONFIG_PATH
        value: {{ .Values.config.mountPath }}
    volumeMounts:
      - name: gateway-config
        mountPath: {{ .Values.config.mountPath }}
        readOnly: true
```

**Hot-reload flow** (asya-j2vk):

```
ConfigMap update (kubectl/CLI)
  -> Kubelet syncs volume (up to 60s)
    -> fsnotify detects file change
      -> Debounce (500ms)
        -> LoadFromDir(configPath)
          -> Validate()
            -> Rebuild MCP tool registry (thread-safe swap)
            -> Rebuild A2A skill registry (thread-safe swap)
            -> Regenerate Agent Card (cached)
              -> Log tool/skill additions/removals
```

**Thread-safe registry swap**: Both registries use atomic pointer swap (`atomic.Value` in Go) so that in-flight requests complete with the old registry while new requests use the updated one.

### 9.3 Agent Card Construction

The Agent Card is **generated at runtime** from the loaded config, not stored as a static file. It is regenerated on every config reload and cached until the next change.

**Construction logic** (pseudocode):

```go
func BuildAgentCard(cfg *config.Config, publicURL string) *AgentCard {
    card := &AgentCard{
        Name:        cfg.A2A.Name,
        Description: cfg.A2A.Description,
        Version:     cfg.A2A.Version,
        Provider:    cfg.A2A.Provider,
        SupportedInterfaces: []AgentInterface{{
            URL:             publicURL + "/a2a/",
            ProtocolBinding: "jsonrpc-over-http",
            ProtocolVersion: "0.2.6",
        }},
        Capabilities: AgentCapabilities{
            Streaming:         true,
            PushNotifications: false,
        },
        DefaultInputModes:  []string{"application/json"},
        DefaultOutputModes: []string{"application/json"},
    }

    for _, tool := range cfg.Tools {
        if !tool.IsA2AEnabled() {
            continue
        }
        a2aCfg := tool.GetA2AConfig()
        card.Skills = append(card.Skills, AgentSkill{
            ID:          tool.Name,
            Name:        humanize(tool.Name),
            Description: tool.Description,
            Tags:        a2aCfg.Tags,
            InputModes:  a2aCfg.InputModes,
            OutputModes: a2aCfg.OutputModes,
            Examples:    a2aCfg.Examples,
        })
    }
    return card
}
```

## 10. Sidecar Changes for A2A

The sidecar operates identically regardless of whether a task was created via MCP or A2A. However, several enhancements support richer A2A semantics.

### 10.1 Streaming Event Forwarding

**Prerequisite**: asya-qrsp (multi-frame streaming protocol) and asya-n5mc (HTTP streaming events to gateway).

When the runtime sends `stream` frames (multi-frame protocol), the sidecar forwards them to the gateway:

```
Runtime                    Sidecar                    Gateway
  |                          |                          |
  |-- {type:stream, data:{   |                          |
  |    type:text_delta,      |                          |
  |    delta:"analyzing"}} ->|                          |
  |                          |-- POST /tasks/{id}/events|
  |                          |   {type:text_delta,      |
  |                          |    delta:"analyzing"} -->|
  |                          |                          |-- SSE broadcast
  |                          |                          |   artifact_update
  |-- {type:result,          |                          |
  |   data:{payload:{...},   |                          |
  |         route:{...}}} -->|                          |
  |                          |-- Route to next queue    |
```

**Event forwarding is fire-and-forget**: The sidecar does not wait for gateway acknowledgment. If the gateway is unavailable, the event is logged and dropped. This preserves the sidecar's non-blocking message processing guarantee.

### 10.2 Artifact Reporting

Currently, happy-end stores results in S3 and reports a flat `result` field to the gateway. For A2A artifact support, the final status report is extended:

```json
{
  "id": "task-789",
  "status": "succeeded",
  "result": {"themes": ["revenue"], "sentiment": "positive"},
  "artifacts": [
    {
      "artifact_id": "result-1",
      "name": "Analysis Result",
      "parts": [{"data": {"themes": ["revenue"], "sentiment": "positive"}}]
    },
    {
      "artifact_id": "s3-output",
      "name": "Full Report",
      "parts": [{"url": "s3://bucket/results/task-789.json", "media_type": "application/json"}]
    }
  ],
  "metadata": {"s3_uri": "s3://bucket/results/task-789.json"}
}
```

**Backward compatibility**: The `result` field is kept for MCP consumers. The `artifacts` array is new and ignored by older gateway versions.

### 10.3 Task Cancellation Support

The sidecar already polls `GET /tasks/{id}/active` before processing. This endpoint returns `410 Gone` for completed or failed tasks. Extending for cancellation:

**Gateway change**: `HandleTaskActive` returns `410 Gone` for `canceled` status (in addition to `succeeded` and `failed`).

**Sidecar behavior on 410**:
1. Ack the current message (prevent DLQ)
2. Do not route to next actor
3. Log cancellation at INFO level
4. Report final status as `canceled` to gateway

No changes to the runtime or user handlers --- cancellation is transparent to actors.

## 11. Streaming Architecture

### 11.1 A2A Streaming Response Format

A2A streaming uses SSE with `StreamResponse` events. Each event has one of 4 types:

```
+------------------------------------------+
| StreamResponse (oneof)                    |
+------------------------------------------+
| task              -> Initial Task object  |
| message           -> Direct response      |
| status_update     -> TaskStatusUpdateEvent|
| artifact_update   -> TaskArtifactUpdateEvent|
+------------------------------------------+
```

**SSE event naming**: The `event:` field in SSE corresponds to the `oneof` variant name:

```
event: task
data: {...Task JSON...}

event: status_update
data: {...TaskStatusUpdateEvent JSON...}

event: artifact_update
data: {...TaskArtifactUpdateEvent JSON...}
```

### 11.2 Mapping Sidecar Events to A2A Stream Events

The gateway's SSE subscriber receives `TaskUpdate` events from the TaskStore. The A2A handler translates:

```go
func translateToA2AStreamEvent(update TaskUpdate) StreamResponse {
    switch {
    case update.Status == TaskStatusPending:
        // Initial task creation
        return StreamResponse{Task: buildA2ATask(update)}

    case update.TaskState != nil:
        // Progress update from sidecar
        statusMsg := buildProgressMessage(update)
        return StreamResponse{StatusUpdate: &TaskStatusUpdateEvent{
            TaskID:    update.ID,
            ContextID: update.ContextID,
            Status: TaskStatus{
                State:   mapToA2AState(update.Status),
                Message: statusMsg,
            },
        }}

    case update.Status == TaskStatusSucceeded:
        // Final success: emit artifact_update then status_update
        ...

    case update.Status == TaskStatusFailed:
        return StreamResponse{StatusUpdate: &TaskStatusUpdateEvent{
            TaskID:    update.ID,
            ContextID: update.ContextID,
            Status: TaskStatus{
                State:   "failed",
                Message: buildErrorMessage(update),
            },
        }}
    }
}
```

### 11.3 Multi-Frame Runtime Protocol Integration

The multi-frame runtime protocol (asya-qrsp) introduces `stream` and `result` frame types:

```
Runtime -> Sidecar:  {"type": "stream", "data": {"type": "text_delta", "delta": "..."}}
Runtime -> Sidecar:  {"type": "stream", "data": {"type": "progress", "pct": 50}}
Runtime -> Sidecar:  {"type": "result", "data": {"payload": {...}, "route": {...}}}
```

When the sidecar receives `stream` frames and forwards them to the gateway via `POST /tasks/{id}/events`, the gateway translates them into A2A `TaskArtifactUpdateEvent`:

```json
{
  "taskId": "task-789",
  "contextId": "ctx-abc",
  "artifact": {
    "artifactId": "stream-0",
    "parts": [{"text": "analyzing the quarterly..."}]
  },
  "append": true,
  "lastChunk": false
}
```

The `append: true` + `lastChunk: false` pattern allows clients to reconstruct the full streaming output incrementally. When the `result` frame arrives, a final `artifact_update` with `lastChunk: true` is sent.

## 12. Authentication

**Phase 2** --- implemented via authentication middleware (asya-wir).

The A2A spec supports multiple security schemes declared in the Agent Card. The gateway implements:

**Phase 2a: API Key** (simplest, for initial rollout):

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

**Gateway configuration** (env var):
- `ASYA_A2A_API_KEY`: Static API key for A2A endpoint access
- Applied to `/a2a/*` routes only; `/mcp` and internal `/tasks/*` remain unauthenticated

**Phase 2b: Bearer Token** (JWT validation):

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

**Phase 3: OAuth2** (full enterprise):

```json
{
  "securitySchemes": {
    "oauth2": {
      "oauth2SecurityScheme": {
        "flows": {
          "clientCredentials": {
            "tokenUrl": "https://auth.example.com/token",
            "scopes": {
              "a2a:read": "Read tasks",
              "a2a:write": "Create and cancel tasks"
            }
          }
        }
      }
    }
  }
}
```

**Middleware architecture**:

```go
// Applied to /a2a/* routes only
func A2AAuthMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        // Check API Key, Bearer, or OAuth2 depending on config
        if !authenticate(r) {
            writeA2AError(w, -32005, "Authentication required")
            return
        }
        next.ServeHTTP(w, r)
    })
}
```

## 13. Implementation Phases

### Phase 0: Prerequisites (in progress)

| Task | Bead | Status | Description |
|---|---|---|---|
| Rename envelope to task | asya-uic | In Progress | Terminology alignment across gateway |

### Phase 1: Core A2A (MVP)

Delivers: Agent Card discovery, basic message sending, SSE streaming. An external A2A client can discover the gateway, send a message to a skill, and stream the result.

| Task | Bead | Priority | Description |
|---|---|---|---|
| Agent Card endpoint | asya-4c1 | P2 | `GET /.well-known/agent.json` generated from config |
| Config schema extension | (new) | P2 | Add `a2a` section to Config struct, `a2a` field to Tool |
| A2A skill registry | (new) | P2 | Parallel to MCP tool registry, skill -> flow resolution |
| POST /a2a/ (SendMessage) | asya-u76 | P2 | SendMessage with skill resolution, task creation |
| POST /a2a/ (streaming) | asya-ey0 | P2 | SendStreamingMessage with SSE |
| GET /a2a/tasks/{id} | asya-2n8 | P2 | GetTask with A2A format |
| GET /a2a/tasks/{id}:subscribe | asya-z80 | P2 | SubscribeToTask (SSE) |
| A2A error format | asya-71m | P2 | JSON-RPC error codes |
| fsnotify hot-reload | asya-j2vk | P2 | Config watch + registry rebuild |

**Estimated scope**: ~800-1200 lines of Go (new `internal/a2a/` package).

### Phase 2: Production Readiness

Delivers: Authentication, task listing/cancellation, context grouping, streaming events from sidecars.

| Task | Bead | Priority | Description |
|---|---|---|---|
| Authentication middleware | asya-wir | P2 | API Key + Bearer for `/a2a/*` |
| GET /a2a/tasks (list) | asya-ahb | P3 | ListTasks with pagination + filters |
| POST /a2a/tasks/{id}:cancel | asya-78f | P3 | CancelTask + sidecar support |
| context_id support | asya-r52 | P2 | DB migration, query support, multi-turn |
| Sidecar terminology | asya-57s | P2 | Log/metric alignment |
| Artifact model | (new) | P2 | DB table, TaskStore methods |
| POST /tasks/{id}/events | (new) | P2 | Streaming event forwarding |

**Dependencies**: asya-qrsp (multi-frame protocol) should land before or in parallel.

### Phase 3: Advanced Features

Delivers: Human-in-the-loop, AG-UI integration.

| Task | Bead | Priority | Description |
|---|---|---|---|
| input_required state | asya-r7d | P2 | Pause/resume task for human input |
| AG-UI event streaming | asya-0wr | P2 | UI-facing event stream |
| AG-UI event mapping | asya-qyu | P2 | Map Asya events to AG-UI types |

### Phase 4: Extended Protocol

Delivers: Push notifications, gRPC, A2UI.

| Task | Bead | Priority | Description |
|---|---|---|---|
| Push notification CRUD | asya-ly9 | P4 | Webhook registration + delivery |
| gRPC transport | asya-ybm | P3 | gRPC binding from proto |
| A2UI payload support | asya-53w | P4 | Optional UI protocol |

## 14. Testing Strategy

### Unit Tests

| Component | What to Test | Location |
|---|---|---|
| A2A config parsing | YAML with a2a fields, backward compat | `src/asya-gateway/internal/config/` |
| Agent Card generation | Config -> AgentCard, skill filtering | `src/asya-gateway/internal/a2a/` |
| Message -> payload mapping | Part extraction, `_a2a_*` fields | `src/asya-gateway/internal/a2a/` |
| TaskUpdate -> StreamResponse | Event translation for all states | `src/asya-gateway/internal/a2a/` |
| State mapping | Asya <-> A2A state transitions | `src/asya-gateway/internal/a2a/` |
| Skill resolution | Hint-based, task continuation | `src/asya-gateway/internal/a2a/` |

### Component Tests (Docker Compose)

| Test | What to Verify |
|---|---|
| Agent Card served correctly | `GET /.well-known/agent.json` returns valid card |
| SendMessage creates task | POST -> task in TaskStore -> message in queue |
| SendStreamingMessage SSE | POST -> SSE events match A2A format |
| GetTask format | A2A response format with status, artifacts, history |
| Config hot-reload | Update ConfigMap -> skills change -> Agent Card updates |
| Auth middleware blocks unauthenticated | 401/403 for `/a2a/*` without credentials |

### Integration Tests (Docker Compose, multi-component)

| Test | What to Verify |
|---|---|
| A2A end-to-end flow | SendMessage -> actor processing -> SSE result |
| Skill + MCP parity | Same flow callable via both protocols |
| Task cancellation | Cancel -> sidecar stops routing |
| Multi-turn conversation | Same context_id -> grouped history |

### E2E Tests (Kind cluster)

| Test | What to Verify |
|---|---|
| Agent Card with real AsyncActors | Skills match deployed flows |
| ConfigMap update -> hot-reload | kubectl patch -> new skill appears |
| Cross-namespace flows | Gateway routes to correct namespace |
| Authentication enforcement | API Key required for A2A, not for MCP |

## 15. Open Questions

1. **JSON-RPC vs REST for A2A endpoints**: A2A specifies JSON-RPC 2.0 as the primary binding. Should `/a2a/` accept JSON-RPC requests (method + params) or REST-style bodies? The spec supports both, but JSON-RPC is normative. **Recommendation**: JSON-RPC primary at `POST /a2a/`, with REST convenience routes at `/a2a/tasks/{id}` for GET operations.

2. **Skill resolution without explicit hint**: When a message arrives without `metadata["asya.sh/skill"]`, how should the gateway resolve which skill to invoke? Options:
   - Reject with error (simplest, Phase 1)
   - Match against skill descriptions using text similarity
   - Use an LLM for intent classification (smart gateway pattern)

   **Recommendation**: Reject in Phase 1, add intent matching in Phase 3.

3. **Multi-namespace A2A**: Should the Agent Card expose skills from multiple namespaces? Currently the gateway connects to one namespace's queues. Options:
   - Single-namespace (Phase 1)
   - Multi-namespace via config (list of namespaces + queue prefixes)

   **Recommendation**: Single-namespace in Phase 1, config-driven multi-namespace in Phase 2.

4. **Artifact storage backend**: A2A artifacts need persistent storage. Options:
   - Store in PostgreSQL `task_artifacts` table (simple, bounded)
   - Reference S3 URIs only (existing happy-end pattern)
   - Hybrid: metadata in PG, content in S3

   **Recommendation**: Hybrid --- small structured artifacts in PG, large files as S3 references.

5. **`message/send` vs `message/stream` endpoint**: The A2A spec uses the same endpoint with different methods. Should we use a single `POST /a2a/` endpoint and dispatch by JSON-RPC method name, or separate REST-style endpoints?

   **Recommendation**: Single `POST /a2a/` endpoint dispatching by method name (matches JSON-RPC convention and A2A spec).

6. **Backward compatibility of internal `/tasks/*` endpoints**: The internal sidecar-facing endpoints (`/tasks/{id}/progress`, `/tasks/{id}/final`) use different response formats than A2A. Should these be migrated to A2A format?

   **Recommendation**: No. Keep internal endpoints as-is. They are not user-facing and changing them would require sidecar changes across all deployed versions.

7. **A2A protocol version negotiation**: A2A uses `A2A-Version` header. How to handle version mismatches?

   **Recommendation**: Accept current version (0.2.x), return `A2A-Version` in response headers. Reject unsupported versions with `-32600` error.

---

## Appendix A: A2A Proto -> Asya Go Type Mapping

| A2A Proto Type | Asya Go Type | Location |
|---|---|---|
| `Task` | `a2a.Task` | `internal/a2a/types.go` |
| `TaskState` | `a2a.TaskState` | `internal/a2a/types.go` |
| `TaskStatus` | `a2a.TaskStatus` | `internal/a2a/types.go` |
| `Message` | `a2a.Message` | `internal/a2a/types.go` |
| `Part` | `a2a.Part` | `internal/a2a/types.go` |
| `Artifact` | `a2a.Artifact` | `internal/a2a/types.go` |
| `AgentCard` | `a2a.AgentCard` | `internal/a2a/types.go` |
| `AgentSkill` | `a2a.AgentSkill` | `internal/a2a/types.go` |
| `StreamResponse` | `a2a.StreamResponse` | `internal/a2a/types.go` |
| `TaskStatusUpdateEvent` | `a2a.TaskStatusUpdateEvent` | `internal/a2a/types.go` |
| `TaskArtifactUpdateEvent` | `a2a.TaskArtifactUpdateEvent` | `internal/a2a/types.go` |
| `SendMessageRequest` | `a2a.SendMessageRequest` | `internal/a2a/types.go` |
| `SendMessageConfiguration` | `a2a.SendMessageConfig` | `internal/a2a/types.go` |

Types are manually defined in Go (not generated from proto) to avoid the protobuf dependency. JSON tags use camelCase per A2A JSON convention.

## Appendix B: File Structure

```
src/asya-gateway/
|-- internal/
|   |-- a2a/                    # NEW: A2A protocol implementation
|   |   |-- types.go            # A2A data types (AgentCard, Task, Message, etc.)
|   |   |-- handler.go          # HTTP handler for /a2a/ endpoints
|   |   |-- registry.go         # Skill registry (parallel to MCP tool registry)
|   |   |-- card.go             # Agent Card generation from config
|   |   |-- translate.go        # TaskUpdate <-> StreamResponse translation
|   |   `-- auth.go             # Authentication middleware
|   |-- config/
|   |   |-- routes.go           # MODIFIED: Add A2AConfig, A2ASkillConfig
|   |   |-- loader.go           # MODIFIED: Load a2a section
|   |   `-- watcher.go          # NEW: fsnotify file watcher
|   |-- mcp/                    # UNCHANGED
|   |-- taskstore/
|   |   |-- interface.go        # MODIFIED: Add List(), artifact methods
|   |   |-- store.go            # MODIFIED: Add List(), artifacts
|   |   `-- pg_store.go         # MODIFIED: Add List(), artifacts, context_id
|   `-- queue/                  # UNCHANGED
|-- pkg/types/
|   `-- task.go                 # MODIFIED: Add canceled, input_required, rejected states
|-- cmd/gateway/
|   `-- main.go                 # MODIFIED: Register /a2a/ routes, /.well-known/
`-- db/deploy/
    |-- 004_add_context_id.sql      # NEW: Add context_id column
    `-- 005_add_task_artifacts.sql  # NEW: Artifacts table
```
