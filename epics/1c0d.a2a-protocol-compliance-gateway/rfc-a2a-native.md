# RFC: Native A2A Protocol Support for Asya Gateway

**Status**: Draft
**Date**: 2026-03-02
**Epic**: 1c0d (A2A Protocol Compliance for Gateway)
**Supersedes**: Sections of `epic.md` (original A2A RFC) and `rfc.md` (expose flows)
**Related**: 1mx1 (meshage rename), 1ixy (pause-resume), 1l01 (ABI protocol), 1dmf (stateful actors)

---

## Table of Contents

- [1. Abstract](#1-abstract)
- [2. Motivation](#2-motivation)
- [3. Terminology](#3-terminology)
- [4. Conceptual Mapping: Asya to A2A](#4-conceptual-mapping-asya-to-a2a)
- [5. Data Model](#5-data-model)
  - [5.1 Task State Machine](#51-task-state-machine)
  - [5.2 Message-to-Meshage Translation](#52-message-to-meshage-translation)
  - [5.3 Artifact Model](#53-artifact-model)
  - [5.4 History in Meshage Payload](#54-history-in-meshage-payload)
  - [5.5 Context as Grouping Attribute](#55-context-as-grouping-attribute)
  - [5.6 ID Scheme](#56-id-scheme)
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
- [9. Streaming Architecture](#9-streaming-architecture)
  - [9.1 FLY to A2A StreamResponse Mapping](#91-fly-to-a2a-streamresponse-mapping)
  - [9.2 SSE Event Format](#92-sse-event-format)
  - [9.3 Actor-to-Client Streaming Flow](#93-actor-to-client-streaming-flow)
  - [9.4 Blocking Mode](#94-blocking-mode)
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
meshage dispatch, and the `TaskStore` interface to wrap the existing PostgreSQL
store. The `a2a-go` library handles JSON-RPC dispatch, SSE formatting, request
validation, and protocol compliance. Asya's internal architecture (meshages,
sidecars, actors, queues) remains unchanged.

The A2A endpoint prefix is configurable via `ASYA_A2A_PREFIX` (default: `/a2a`, next to `/mcp`).
In future, we'll implement api versioning with prefixes like `/api/v1`.

Note: still, A2A protocol requires to host in the root: `/.well-known/agent-card.json`.

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
| **Meshage** | Asya's internal envelope traveling through the actor mesh. Contains `id`, `route`, `payload`, `status`, `headers`. Lives in queues (in-transit) or S3 (paused). Formerly "message" or "envelope" (see epic 1mx1). |
| **Task** | Gateway's metadata record tracking a meshage's lifecycle in PostgreSQL. Has `id`, `context_id`, `status`, `artifacts`, `timestamps`. The A2A-facing representation of work. |
| **Context** (`context_id`) | A grouping attribute on tasks. Groups related tasks in a conversation/session. Just a TEXT column — not a first-class entity. Server-generated UUID if not provided by client. |
| **Message** (A2A) | An immutable communication turn with `role` (user/agent), `parts`, `message_id`. Lives in meshage `payload.a2a.history`. |
| **Artifact** (A2A) | A structured output from a task. Contains `parts` (text, data, file references). Stored in external storage. |
| **Skill** (A2A) | A named capability in the Agent Card. Maps to an exposed actor/flow in the `tools` table. |
| **Tool** (MCP) | A named capability in MCP `tools/list`. Same backing data as a Skill. |
| **FLY** | ABI yield verb for upstream streaming: `yield "FLY", {...}`. Delivers events from actor → runtime → sidecar → gateway → SSE client. |

---

## 4. Conceptual Mapping: Asya to A2A

### 4.1 Entity Mapping

| A2A Concept | Asya Mapping | Notes |
|-------------|-------------|-------|
| **Context** (`contextId`) | TEXT column on tasks table | Grouping key for conversations. One context can have many tasks. Server-generated UUID if not provided. |
| **Task** | Gateway task record in PostgreSQL | 1:1 with a meshage lifecycle. Tracks status, artifacts, metadata. |
| **Message** (client → server) | Creates meshage or resumes paused task | User input dispatched to the actor mesh. |
| **Message** (server → client, streaming) | FLY event in A2A StreamResponse format | Ephemeral upstream delivery via ABI. Not persisted by gateway. |
| **Message** (server → client, history) | Stored in `payload.a2a.history` in meshage | Canonical turns survive pause/resume via S3. |
| **Artifact** | `task_artifacts` table in gateway DB | Final outputs from x-sink, or streaming chunks via FLY. |
| **Skill** | Exposed actor/flow in `tools` table | `WHERE a2a_enabled = true`. Maps to entrypoint actor. |
| **AgentCard** | Generated dynamically from `tools` table | Cached in memory, regenerated on tool registry change. |

### 4.2 Lifecycle Mapping

A2A Task lifecycle maps to meshage lifecycle:

```
Client                    Gateway                     Actor Mesh
  |                         |                            |
  |-- SendMessage --------->|                            |
  |                         |-- Create Task (DB) ------->|
  |                         |-- Create Meshage --------->|
  |                         |-- Dispatch to queue ------>|
  |<-- Task{submitted} -----|                            |
  |                         |                            |
  |                         |<-- /mesh/{id}/progress ----|  (sidecar reports)
  |<-- StatusUpdate{working}|                            |
  |                         |                            |
  |                         |<-- FLY events ------------|  (actor streams)
  |<-- ArtifactUpdate ------|                            |
  |                         |                            |
  |                         |<-- /mesh/{id}/final -------|  (x-sink reports)
  |<-- StatusUpdate{done} --|                            |
  |                         |-- Create Artifact (DB) --->|
```

### 4.3 Why Task:Meshage is 1:1

Each A2A Task corresponds to exactly one meshage lifecycle. When a meshage is
paused and later resumed:

- The meshage ID stays the same (x-resume loads the original meshage from S3)
- The task ID stays the same
- A NEW resume meshage is created and sent to x-resume, but x-resume merges it
  into the original meshage, continuing with the original ID

Multiple tasks in the same context are independent meshages with different IDs,
sharing only the `context_id` attribute.

---

## 5. Data Model

### 5.1 Task State Machine

A2A defines 9 task states. Asya's internal states map as follows (note: `TaskStatus` to be renamed to `MeshageStatus`):

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

### 5.2 Message-to-Meshage Translation

When the gateway receives an A2A `SendMessageRequest`, it translates the A2A
`Message` into a meshage `payload` and stamps A2A metadata in meshage `headers`.

**Inbound translation** (A2A Message → meshage payload):

```
A2A Message {                       Meshage {
  message_id: "m-001",                id: "task-uuid",
  context_id: "c-001",                route: {prev:[], curr:"entrypoint", next:[]},
  role: "user",                        headers: {
  parts: [                              "x-asya-task-id": "task-uuid",
    {text: "Analyze this"},              "x-asya-context-id": "c-001",
    {data: {format: "pdf"}},             "x-asya-skill": "analyze-doc"
    {url: "s3://b/f.pdf",             },
     media_type: "application/pdf"}    payload: {
  ]                                      "a2a": {
}                                          "history": [
                                             {
                                               "message_id": "m-001",
                                               "role": "user",
                                               "parts": [
                                                 {"text": "Analyze this"},
                                                 {"data": {"format": "pdf"}},
                                                 {"url": "s3://b/f.pdf",
                                                  "media_type": "application/pdf"}
                                               ]
                                             }
                                           ]
                                         },
                                         "query": "Analyze this",
                                         "format": "pdf",
                                         "_a2a_files": [
                                           {"url": "s3://b/f.pdf",
                                            "media_type": "application/pdf"}
                                         ]
                                       }
                                     }
```

**Payload construction rules** (applied in order):

1. **Single data Part only**: Unwrap `data.Value` directly as the payload root.
   This is the most common case for structured API calls.
   ```json
   parts: [{data: {query: "...", depth: 3}}]
   → payload: {a2a: {history: [...]}, query: "...", depth: 3}
   ```

2. **Text Parts**: Concatenate with `\n`, store in `query` field (or `_a2a_text`
   if `query` already exists from a data Part).
   ```json
   parts: [{text: "Analyze this"}]
   → payload: {a2a: {history: [...]}, query: "Analyze this"}
   ```

3. **File Parts**: Collect into `_a2a_files` array.

4. **Mixed Parts**: Combine all rules above.

5. **Always**: Append the full A2A Message (with all parts) to
   `payload.a2a.history`.

**Outbound translation** (meshage result → A2A Artifact): See Section 5.3.

### 5.3 Artifact Model

A2A Artifacts are structured task outputs stored in the gateway DB.

**When artifacts are created**:

| Source | Trigger | Artifact Content |
|--------|---------|------------------|
| x-sink final result | `POST /mesh/{id}/final` with `status: succeeded` | `DataPart` wrapping the result JSON |
| x-sink S3 reference | `POST /mesh/{id}/final` with S3 URI in metadata | `FilePart` with URL + media type |
| FLY streaming chunk | FLY event with `artifact_update` | Streaming artifact (append mode) |

**Translation** (meshage result → Artifact):

```go
func resultToArtifact(taskID string, result any, s3URI string) *a2a.Artifact {
    artifact := &a2a.Artifact{
        ID:   a2a.ArtifactID(taskID + "-result"),
        Name: "Result",
    }

    // Structured result → DataPart
    if result != nil {
        artifact.Parts = append(artifact.Parts, &a2a.Part{
            Content:   &a2a.Data{Value: result},
            MediaType: "application/json",
        })
    }

    // S3 file → FilePart
    if s3URI != "" {
        artifact.Parts = append(artifact.Parts, &a2a.Part{
            Content:   a2a.URL(s3URI),
            MediaType: "application/json",
        })
    }

    return artifact
}
```

**Database storage**: See Section 13 for schema.

### 5.4 History in Meshage Payload

A2A conversation history lives in the meshage payload at `payload.a2a.history`.
This is a list of A2A Message objects (using A2A's native format).

```json
{
  "a2a": {
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
    ]
  },
  "query": "Focus on revenue trends",
  "context": "Analyze this data"
}
```

**Why meshage payload, not gateway DB**:

- History travels with the meshage through the actor mesh. Actors that need
  multi-turn context can read `payload.a2a.history` directly.
- On pause (x-pause), the full meshage (including history) is persisted to S3.
  On resume (x-resume), history is restored with the meshage.
- The gateway does not store a separate copy of history.

**Implications for GetTask**:

- `GetTask(historyLength=N)` returns history from the meshage state.
- For **in-flight tasks**: history is in the queue message. Gateway returns
  `history: []`. Streaming (SubscribeToTask) covers the real-time case.
- For **paused tasks**: history is in S3. Gateway fetches from S3 on demand.
- For **completed tasks**: history is in x-sink's S3 result. Gateway fetches
  from S3 on demand.
- A2A spec marks `history` as optional (`repeated Message`, not REQUIRED).
  This gap is acceptable.

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
- Multiple tasks in the same context are independent meshages. They share only
  the grouping key.

**Cross-task context sharing**: If an actor needs to reference previous tasks'
results in the same context (e.g., multi-turn agent memory), it uses the state
proxy (RFC 1dmf) with `context_id` as a storage key. This is actor-level business
logic, not A2A protocol logic.

### 5.6 ID Scheme

**Task ID = Meshage ID** (same UUID). The gateway generates the ID and uses it
for both the task record and the meshage envelope. This is the current behavior
and avoids sidecar changes.

Additionally, the gateway stamps A2A metadata in meshage headers:

```json
{
  "headers": {
    "x-asya-task-id": "task-uuid",
    "x-asya-context-id": "ctx-uuid",
    "x-asya-skill": "analyze-doc"
  }
}
```

Actors can read these via ABI: `yield "GET", ".headers.x-asya-context-id"`.

---

## 6. Gateway Architecture

### 6.1 Endpoint Layout

The A2A endpoint prefix is configurable:

```
ASYA_A2A_PREFIX=""       →  POST /message:send, GET /tasks/{id}, ...
ASYA_A2A_PREFIX="/a2a"   →  POST /a2a/message:send, GET /a2a/tasks/{id}, ...
```

**Full endpoint map** (with configurable `{prefix}`):

```
asya-gateway
├── {prefix}/message:send             # SendMessage (POST, JSON-RPC)
├── {prefix}/message:stream           # SendStreamingMessage (POST, SSE response)
├── {prefix}/tasks/{id}               # GetTask (GET)
├── {prefix}/tasks                    # ListTasks (GET)
├── {prefix}/tasks/{id}:cancel        # CancelTask (POST)
├── {prefix}/tasks/{id}:subscribe     # SubscribeToTask (GET, SSE)
├── {prefix}/tasks/{id}/pushNotificationConfigs          # Push CRUD
├── {prefix}/tasks/{id}/pushNotificationConfigs/{cfgId}  # Push Get/Delete
├── {prefix}/extendedAgentCard        # GetExtendedAgentCard (GET)
│
├── /.well-known/a2a/agent-card       # Agent Card discovery (GET)
│
├── /mcp                              # MCP Streamable HTTP (unchanged)
├── /mcp/sse                          # MCP SSE deprecated (unchanged)
├── /tools/call                       # REST tool invocation (unchanged)
├── /tools/expose                     # Register tool/skill (POST)
├── /tools                            # List tools (GET)
├── /tools/{name}                     # Remove tool (DELETE)
│
├── /mesh/{id}/progress               # Sidecar progress reporting (POST)
├── /mesh/{id}/final                  # End actor final status (POST)
├── /mesh/{id}/active                 # Sidecar liveness check (GET)
├── /mesh/{id}/stream                 # SSE streaming (GET, internal)
├── /mesh/{id}/partial                # Partial event payload (POST)
├── /mesh                             # Fanout child creation (POST)
│
└── /health                           # Health check (GET)
```

**Design decision**: A2A paths follow the protobuf HTTP annotations exactly
(`/message:send`, `/tasks/{id}:cancel`, etc.). The prefix is applied uniformly.
When `ASYA_A2A_PREFIX=""` (default), the paths match the A2A spec. When set to
`/a2a`, they are namespaced to avoid collision with `/mesh/` routes.

**Collision avoidance**: The internal sidecar-facing routes are at `/mesh/*`
(renamed from `/tasks/*` per epic 1mx1). The A2A routes at `/tasks/*` (or
`/a2a/tasks/*`) are client-facing. No collision.

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
| `a2asrv.AgentExecutor` | `internal/a2a/executor.go` | Translates A2A Messages → meshages, dispatches to queue |
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

    // 2. Translate A2A Message → meshage payload
    payload := messageToPayload(msg)

    // 3. Create meshage with A2A metadata in headers
    meshage := &types.Task{
        ID:        string(taskInfo.TaskID),
        ContextID: taskInfo.ContextID,
        Status:    types.TaskStatusPending,
        Route: types.Route{
            Prev: []string{},
            Curr: skill.Actor,
            Next: []string{},
        },
        Headers: map[string]any{
            "x-asya-task-id":    string(taskInfo.TaskID),
            "x-asya-context-id": taskInfo.ContextID,
            "x-asya-skill":      skill.Name,
        },
        Payload: payload,
    }

    // 4. Dispatch to actor queue
    if err := e.queueClient.SendMessage(ctx, meshage); err != nil {
        return e.writeFailure(queue, taskInfo, err)
    }

    // 5. Write initial "submitted" event
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
**HTTP**: `POST {prefix}/message:send`

**Flow**:

1. Parse `SendMessageRequest` (handled by a2a-go)
2. Extract `Message` and optional `SendMessageConfiguration`
3. If `message.task_id` set and task is paused → resume flow (Section 10.3)
4. If `message.task_id` set and task is not paused → append to existing task
5. If no `task_id` → resolve skill, create new task, dispatch meshage
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
**HTTP**: `POST {prefix}/message:stream`

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
**HTTP**: `GET {prefix}/tasks/{id}`

Returns the current state of a task.

**Parameters**:

- `id` (REQUIRED): Task ID
- `history_length` (optional): Max number of history messages to return

**Response**: `a2a.Task` with status, artifacts, and optionally history.

**History retrieval** (since history lives in meshage payload):

- In-flight tasks: `history: []` (not available from queues)
- Paused/completed tasks: Fetch from S3 on demand, return last N messages
- If S3 fetch fails or history unavailable: `history: []` (field is optional)

### 7.4 ListTasks

**Method**: `tasks/list`
**HTTP**: `GET {prefix}/tasks`

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
**HTTP**: `POST {prefix}/tasks/{id}:cancel`

**Flow**:

1. Validate task exists and is not in terminal state
2. Set task status to `canceled` in TaskStore
3. Sidecar discovers on next `GET /mesh/{id}/active` → receives `410 Gone`
4. Sidecar acks current message, does not route to next actor
5. Return updated Task with `status.state: CANCELED`

**Error**: `TaskNotCancelableError` if task is already terminal.

### 7.6 SubscribeToTask

**Method**: `tasks/subscribe`
**HTTP**: `GET {prefix}/tasks/{id}:subscribe`

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
| `CreateTaskPushNotificationConfig` | `POST {prefix}/tasks/{id}/pushNotificationConfigs` | Register webhook |
| `GetTaskPushNotificationConfig` | `GET {prefix}/tasks/{id}/pushNotificationConfigs/{cfgId}` | Get config |
| `ListTaskPushNotificationConfigs` | `GET {prefix}/tasks/{id}/pushNotificationConfigs` | List configs |
| `DeleteTaskPushNotificationConfig` | `DELETE {prefix}/tasks/{id}/pushNotificationConfigs/{cfgId}` | Remove |

**Push delivery**: When a task update occurs and push configs exist, the gateway
POSTs the event to the registered webhook URL with the configured authentication
headers.

**Database**: New `task_push_configs` table (see Section 13).

**Implementation phase**: Phase 4 (deferred). The a2a-go handler returns
`PushNotificationNotSupportedError` until implemented. The Agent Card declares
`capabilities.push_notifications: false`.

### 7.8 GetExtendedAgentCard

**Method**: `extendedAgentCard`
**HTTP**: `GET {prefix}/extendedAgentCard`

Returns an authenticated, extended version of the Agent Card with additional
details not publicly visible.

**Implementation phase**: Phase 3. Returns `UnsupportedOperationError` initially.
The Agent Card declares `capabilities.extended_agent_card: false`.

---

## 8. Agent Card and Skill Discovery

### 8.1 Agent Card Structure

Served at `GET /.well-known/a2a/agent-card`. Generated dynamically from the
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
registry changes (POST/DELETE on `/tools/expose`). Cached in memory via atomic
pointer swap.

### 8.2 Skill Registration

Skills are registered through the `tools` table (same as MCP tools). A tool
becomes an A2A skill when `a2a_enabled = true`:

```sql
INSERT INTO tools (name, actor, description, a2a_enabled, a2a_tags, a2a_examples)
VALUES ('analyze-document', 'start-analysis', 'Analyze documents',
        true, '{"analysis","nlp"}', '{"Analyze this report"}');
```

**CLI**:
```bash
asya flow expose my_flow.py \
  --name analyze-document \
  --description "Analyze documents" \
  --a2a \
  --a2a-tags analysis,nlp \
  --a2a-examples "Analyze this report"
```

### 8.3 Skill Resolution Strategy

When a client sends `SendMessage`, the gateway must determine which skill to
invoke. Resolution order:

1. **Explicit skill**: `message.extensions` contains `"asya.sh/skill"` extension,
   and `request.metadata["skill"]` names the skill ID. Exact match against
   `tools.name`.

2. **Task continuation**: `message.task_id` is set → look up the original task's
   skill from `headers.x-asya-skill`.

3. **Single skill default**: If exactly one A2A skill is registered, use it.
   Common for single-purpose deployments.

4. **Reject**: If multiple skills and no hint → return `TaskNotFoundError` with
   message "Skill not specified. Available skills: [list]".

**Future**: LLM-based intent classification (route message text to best-matching
skill). Documented as future extension, not in initial implementation.

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
  |                    |-- upstream SSE ---->|                    |                    |
  |                    |                    |-- POST             |                    |
  |                    |                    |   /mesh/{id}/      |                    |
  |                    |                    |   partial --------->|                    |
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

1. Create task and dispatch meshage (same as non-blocking)
2. Subscribe to task events internally
3. Wait until task reaches terminal state (`COMPLETED`, `FAILED`, `CANCELED`,
   `REJECTED`) or interrupted state (`INPUT_REQUIRED`, `AUTH_REQUIRED`)
4. Return the final `Task` object with artifacts

**Timeout**: Uses the task's `timeout_sec` as the HTTP response timeout. If the
task times out, the gateway returns the task with `status: FAILED`.

---

## 10. Pause/Resume and input_required

### 10.1 Actor-Initiated Pause

When an actor in the pipeline reaches a pause point (via x-pause crew actor),
the meshage is persisted to S3 and the sidecar reports `phase: paused` to the
gateway.

**Actor signals pause** (via ABI):

```python
# The x-pause actor or an inline pause
yield "SET", ".headers.x-asya-pause", json.dumps({
    "prompt": "Review analysis before proceeding",
    "fields": [
        {"name": "approved", "type": "boolean", "prompt": "Approve?"},
        {"name": "notes", "type": "string", "prompt": "Any notes?"}
    ]
})
```

### 10.2 Gateway State Transition

Gateway receives `POST /mesh/{id}/progress` with `status: paused`:

1. Update task status to `paused` (A2A: `INPUT_REQUIRED`)
2. Store pause metadata in `pause_metadata` column
3. Broadcast `TaskStatusUpdateEvent` to SSE subscribers:

```json
{
  "taskId": "t-1",
  "contextId": "c-1",
  "status": {
    "state": "INPUT_REQUIRED",
    "message": {
      "role": "agent",
      "parts": [{"text": "Review analysis before proceeding"}]
    }
  }
}
```

### 10.3 User-Initiated Resume

Client sends `SendMessage` with `task_id` referencing the paused task:

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

**Gateway resume flow**:

1. Look up task by `task_id` — validate status is `paused`
2. Extract user input from Message parts
3. Create resume meshage:
   ```json
   {
     "id": "resume-uuid",
     "route": {"prev": [], "curr": "x-resume", "next": []},
     "headers": {
       "x-asya-resume-task": "t-1",
       "x-asya-task-id": "t-1",
       "x-asya-context-id": "c-1"
     },
     "payload": {"approved": true, "notes": "Looks good"}
   }
   ```
4. Queue to x-resume actor
5. Update task status to `running` (A2A: `WORKING`)
6. Return updated Task

### 10.4 History Accumulation During Pause/Resume

Each turn of a pause/resume conversation adds to `payload.a2a.history`:

1. **Initial send**: User message appended by gateway before dispatching meshage
2. **Actor pause**: Actor can append agent message to history before pausing
   (via `payload.a2a.history.append({role: "agent", parts: [...]})`)
3. **Resume**: Gateway creates resume meshage with user's new message.
   x-resume loads original meshage from S3, appends resume message to history,
   merges user input into payload, continues route.

**x-resume merge logic**:

```python
def resume_handler(payload):
    task_id = yield "GET", ".headers.x-asya-resume-task"
    persisted = load_message(task_id)  # From S3

    # Restore the original payload
    restored = persisted["payload"]

    # Append user's resume input to history
    if "a2a" in payload and "history" in payload["a2a"]:
        restored.setdefault("a2a", {}).setdefault("history", [])
        restored["a2a"]["history"].extend(payload["a2a"]["history"])

    # Merge user input fields (from pause_metadata mapping)
    # ... (same as existing RFC 1ixy)

    # Restore route
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
MCP or A2A. Minimal changes:

1. **Header stamping**: Gateway already stamps `x-asya-task-id` and
   `x-asya-context-id` in meshage headers. Sidecar reads `x-asya-task-id` for
   progress reporting (falls back to `meshage.id` if header missing — backward
   compatible).

2. **FLY forwarding**: FLY events from the runtime are forwarded to
   `POST /mesh/{id}/partial` as-is. The gateway handles the A2A translation.
   No sidecar change needed.

3. **Canceled state**: `GET /mesh/{id}/active` returns `410 Gone` for `canceled`
   status (already returns 410 for `succeeded` and `failed`). Minor code change.

4. **Artifact reporting**: x-sink's `POST /mesh/{id}/final` already sends the
   result. Gateway creates A2A Artifacts from this result. No sidecar change.

---

## 12. Authentication and Security

Authentication applies to A2A endpoints only. Internal `/mesh/*` routes and
MCP `/mcp` remain unauthenticated (internal traffic).

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
`{prefix}/*` routes.

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
// Applied to {prefix}/* routes only
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

### 13.2 Task Artifacts Table

```sql
CREATE TABLE task_artifacts (
    id TEXT PRIMARY KEY,           -- artifact_id
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    name TEXT,                     -- human-readable name
    description TEXT,
    parts JSONB NOT NULL,          -- array of A2A Part objects
    metadata JSONB,
    extensions TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_task_artifacts_task_id ON task_artifacts(task_id);
```

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

### 13.4 Tools Table Extensions

```sql
-- Add A2A-specific columns (may already exist from rfc.md)
ALTER TABLE tools ADD COLUMN IF NOT EXISTS a2a_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE tools ADD COLUMN IF NOT EXISTS a2a_tags TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE tools ADD COLUMN IF NOT EXISTS a2a_input_modes TEXT[] NOT NULL DEFAULT '{application/json}';
ALTER TABLE tools ADD COLUMN IF NOT EXISTS a2a_output_modes TEXT[] NOT NULL DEFAULT '{application/json}';
ALTER TABLE tools ADD COLUMN IF NOT EXISTS a2a_examples TEXT[] NOT NULL DEFAULT '{}';
```

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
| Agent Card endpoint | `GET /.well-known/a2a/agent-card` from tools table | Tools table |
| Skill resolution | Extension-based + single-skill default | Tools table |
| Rename `/tasks/*` to `/mesh/*` | Epic 1mx1 (prereq for path clarity) | Sidecar update |
| DB migration: `context_id`, `task_artifacts` | Schema changes | None |
| FLY A2A-native format | Update sidecar to pass FLY dicts to `/mesh/{id}/partial` | Sidecar |

**Estimated scope**: ~1500 lines of Go (new `internal/a2a/` package refactored
around a2a-go). ~200 lines sidecar changes (URL rename + FLY forwarding).

### Phase 2: Production Readiness

| Task | Description |
|------|-------------|
| API Key authentication | `ASYA_A2A_API_KEY` middleware on `{prefix}/*` |
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
| GetTask history from S3 | Fetch `payload.a2a.history` from S3 for paused/completed |

### Phase 4: Extended Protocol

| Task | Description |
|------|-------------|
| Push notification CRUD | 4 methods + webhook delivery |
| OAuth2 authentication | Client Credentials flow |
| gRPC transport | `a2agrpc.NewHandler()` from a2a-go |

---

## 15. Testing Strategy

### Unit Tests

| Component | What to Test | Location |
|-----------|-------------|----------|
| Message → payload translation | Part extraction, history construction, `_a2a_files` | `internal/a2a/translator_test.go` |
| State mapping | All 9 A2A states ↔ internal states | `internal/a2a/state_test.go` |
| Skill resolution | Extension-based, single-skill default, rejection | `internal/a2a/skill_resolver_test.go` |
| Agent Card generation | Skills filtering, capabilities | `internal/a2a/agent_card_test.go` |
| Store adapter | Internal ↔ A2A task translation | `internal/a2a/store_adapter_test.go` |
| Executor | Meshage creation, resume detection | `internal/a2a/executor_test.go` |

### Component Tests (Docker Compose)

| Test | What to Verify |
|------|---------------|
| Agent Card served | `GET /.well-known/a2a/agent-card` returns valid A2A card |
| SendMessage creates task | POST → task in DB → meshage in queue |
| SendStreamingMessage SSE | POST → SSE events in A2A format |
| GetTask format | A2A response with status, artifacts |
| ListTasks pagination | Cursor-based pagination, context filtering |
| CancelTask | Cancel → sidecar stops routing |
| Auth middleware | 401 for unauthenticated, 200 for authenticated |

### Integration Tests (Docker Compose)

| Test | What to Verify |
|------|---------------|
| A2A end-to-end | SendMessage → actors → SSE result |
| MCP + A2A parity | Same flow callable via both protocols |
| Multi-turn conversation | Same context_id → grouped tasks |
| Pause/resume as input_required | Pause → INPUT_REQUIRED → resume → COMPLETED |
| FLY streaming | Actor FLY → artifact_update SSE events |

### E2E Tests (Kind cluster)

| Test | What to Verify |
|------|---------------|
| Agent Card with real AsyncActors | Skills match deployed flows |
| Cross-namespace routing | Gateway routes to correct namespace |
| Auth enforcement | API Key required for A2A, not for MCP |
| A2A SDK client interop | Official a2a-go client can interact with gateway |

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
- Context ID is available in meshage headers
  (`yield "GET", ".headers.x-asya-context-id"`)
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

// Mount at configurable prefix
prefix := os.Getenv("ASYA_A2A_PREFIX") // "" or "/a2a"
jsonRPCHandler := a2asrv.NewJSONRPCHandler(a2aHandler)

mux.Handle(prefix+"/message:send", jsonRPCHandler)
mux.Handle(prefix+"/message:stream", jsonRPCHandler)
mux.Handle(prefix+"/tasks/", a2aHandler)  // REST routes
mux.Handle(prefix+"/extendedAgentCard", a2aHandler)

// Agent Card at well-known path (always without prefix)
mux.HandleFunc("/.well-known/a2a/agent-card", a2aHandler.AgentCard)
```
