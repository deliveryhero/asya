## RFC: Pause/Resume Actors

> Related: [[1c0d]] (A2A protocol compliance), [[1ixz.typed-handler-signatures]] (typed signatures & payload paths), [[1dmf]] (stateful actors & state proxy).

---

### 1. Overview

#### Problem

Asya pipelines currently run to completion — once a message enters the route, it flows through all actors until it reaches x-sink (success) or x-sump (error). There is no mechanism to:

1. **Pause** a pipeline mid-execution and wait for external input (human-in-the-loop approval, additional data, clarification).
2. **Resume** a paused pipeline with user-provided input merged into the restored payload.
3. **Checkpoint** a message mid-route for crash recovery or long-running workflows.

#### Goal

Introduce two orthogonal capabilities:

- **Checkpoint**: Persist the full message (payload + route + headers) at any point in the pipeline. This is a pure persistence operation — the pipeline may or may not continue.
- **Pause/Resume**: Stop pipeline execution at a checkpoint, transition the task to `paused` phase, and allow external input to restart it.

These capabilities are implemented as crew actors (`x-pause`, `x-resume`) and a header-based signaling protocol between actors, sidecars, and the gateway.

#### Prior Art

| Framework | Mechanism | Input Schema | State Persistence |
|-----------|-----------|--------------|-------------------|
| **A2A Protocol** | `input_required` task state | Flexible `parts` array (text + data) | Protocol-level, unspecified backend |
| **LangGraph** | `interrupt()` + `Command(resume=...)` | No structured schema | Checkpointers (Postgres, MongoDB) |
| **Mastra** | `suspend()` / `resume(resumeData)` | `resumeSchema` (Zod) | Storage providers |
| **Google ADK** | No native HITL | N/A | Session service |

Asya's approach is closest to Mastra's suspend/resume with A2A's protocol-level state mapping.

---

### 2. Architecture

#### 2.1 Message Phases

Add `paused` and `canceled` to the existing phase constants in `src/asya-sidecar/pkg/messages/message.go`:

```go
const (
    PhasePending    = "pending"
    PhaseProcessing = "processing"
    PhaseRetrying   = "retrying"
    PhaseSucceeded  = "succeeded"
    PhaseFailed     = "failed"
    PhasePaused     = "paused"      // NEW
    PhaseCanceled   = "canceled"    // NEW
)
```

**A2A state mapping** (in gateway translator):

| Internal Phase | A2A State |
|----------------|-----------|
| `pending` | `submitted` |
| `processing` | `working` |
| `succeeded` | `completed` |
| `failed` | `failed` |
| `paused` | `input_required` |
| `canceled` | `canceled` |

#### 2.2 Component Roles

```
                    +-------------+
                    |   Gateway   |
                    |             |
                    | - Tracks    |
                    |   task state|
                    | - Accepts   |
                    |   resume    |
                    |   input     |
                    | - Routes to |
                    |   x-resume  |
                    +------+------+
                           |
              +------------+------------+
              |            |            |
         +----v---+  +-----v----+  +---v-----+
         |x-pause |  |x-resume  |  | sidecar |
         |(crew)  |  |(crew)    |  |(per pod) |
         |        |  |          |  |          |
         |Persist |  |Load msg  |  |Reads     |
         |message |  |Merge     |  |x-asya-   |
         |Signal  |  |input     |  |pause hdr |
         |pause   |  |Continue  |  |Reports   |
         |via hdr |  |route     |  |phase     |
         +--------+  +----------+  +----------+
```

**Gateway**: Thin role — tracks task state, accepts resume input from users, routes resume messages to x-resume queue. Does NOT store the message route (that's persisted with the message by x-pause).

**x-pause** (crew actor): Persists the full message to storage (S3/MinIO via state proxy connector). Signals pause via `x-pause` header. Returns `None`.

**x-resume** (crew actor): Receives resume message from gateway (user input as payload). Loads persisted message from storage. Merges user input into restored payload at specified paths (can be configured via env var to do either shallow or deep merge, shallow by default). Sends merged message to the next actor using the restored route.

**Sidecar**: Reads `x-pause` header from runtime response. When present: reports `phase: paused` to gateway, acks message, does NOT route to next actor.

#### 2.3 Checkpoint vs Pause

Checkpointing (persistence) and pausing are orthogonal:

| Scenario | Checkpoint | Pause | Actors in Route |
|----------|------------|-------|-----------------|
| Mid-pipeline save | Yes | No | `[..., checkpointer, next-actor, ...]` |
| Pause for input | Yes | Yes | `[..., x-pause, x-resume, next-actor, ...]` |
| End-of-route save | Yes | No | `[..., last-actor, x-sink]` (existing) |

The `checkpointer` crew actor (see task `debt/1k34nz`) handles pure persistence. `x-pause` extends checkpointing with the pause signal.

---

### 3. Pause Flow (Actor-Initiated)

#### 3.1 Route Configuration

The flow author places `x-pause` and `x-resume` in the route where a pause point is needed:

```yaml
route: [analyzer, x-pause, x-resume, summarizer, x-sink]
```

#### 3.2 x-pause Handler

```python
def pause_handler(payload: dict) -> dict:
    # 1. Persist full message to storage
    persist_message(payload)  # Uses state proxy / S3 connector

    # 2. Signal pause via header
    with open(f"{MSG_ROOT}/headers/x-pause", "w") as f:
        f.write(json.dumps({
            "prompt": "Review this analysis before proceeding",
            "fields": [
                {"name": "approved", "type": "boolean", "prompt": "Approve?"},
                {"name": "notes", "type": "string", "prompt": "Any notes?",
                 "payload_key": "/review/notes"}
            ]
        }))
    
    # 3. Ensure that the next immediate step is x-resume
    with open(f"{MSG_ROOT}/route/next", "r") as f:
        next_step = f.readline()
    if next_step != "

    return {}
```

#### 3.3 x-pause Header Schema

```json
{
  "prompt": "Human-readable description of what input is needed",
  "fields": [
    {
      "name": "field_name",
      "type": "string | boolean | number | array | object",
      "prompt": "Human-readable prompt for this field",
      "payload_key": "/path/to/target",
      "required": true,
      "default": null,
      "options": ["option1", "option2"]
    }
  ]
}
```

**Field properties:**

| Property | Required | Default | Description |
|----------|----------|---------|-------------|
| `name` | Yes | - | Field identifier (used as key in resume input) |
| `type` | Yes | - | JSON Schema primitive type |
| `prompt` | No | - | Human-readable description for UI |
| `payload_key` | No | `/<name>` | `/`-separated path where value lands in restored payload |
| `required` | No | `true` | Whether the field must be provided on resume |
| `default` | No | `null` | Default value if not provided |
| `options` | No | - | Enumerated choices (for multichoice inputs) |

**Path notation** follows RFC [[1ixz.typed-handler-signatures]] section 9:
- `/` — payload root
- `/key` — `payload["key"]`
- `/key/subkey` — `payload["key"]["subkey"]`
- Intermediate dicts are created automatically if they don't exist

**When `payload_key` is omitted**, it defaults to `/<name>`:
```json
{"name": "approved", "type": "boolean"}
```
Equivalent to `"payload_key": "/approved"` — merged at `payload["approved"]`.

#### 3.4 Sidecar Behavior

When sidecar receives a runtime response with `x-pause` header:

1. Parse `x-pause` header value (JSON)
2. Report to gateway: `POST /tasks/{id}/progress` with `phase: paused` and pause metadata
3. Ack the message (remove from queue)
4. Do NOT route to the next actor (x-resume)

The route at this point (after runtime shifting) would be:
```json
{"prev": ["analyzer", "x-pause"], "curr": "x-resume", "next": ["summarizer"]}
```

This route is persisted WITH the message by x-pause (step 3.2), so the gateway doesn't need to store it.

#### 3.5 Gateway State Transition

Gateway receives progress update with `phase: paused`:

1. Update task status to `paused`
2. Store pause metadata (prompt, fields) in `pause_metadata` JSONB column
3. Notify SSE subscribers with `input_required` A2A state
4. Task timeout is suspended (paused tasks don't expire on the original deadline)

---

### 4. Resume Flow

#### 4.1 User Sends Resume Input

Client sends `POST /a2a/` with JSON-RPC:

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": 1,
  "params": {
    "task_id": "task-123",
    "message": {
      "role": "user",
      "parts": [
        {"type": "data", "data": {"approved": true, "notes": "Looks good"}}
      ]
    }
  }
}
```

#### 4.2 Gateway Resume Handler

1. Look up task by `task_id` — validate status is `paused`
2. Extract user input from A2A message parts (same `MessageToPayload` translation)
3. Create new message:
   - **payload**: User input (e.g., `{"approved": true, "notes": "Looks good"}`)
   - **route**: `{prev: [], curr: "x-resume", next: []}`
   - **headers**: `{"x-asya-resume-task": "task-123"}` (so x-resume can find persisted message)
4. Queue message to `x-resume` actor queue
5. Update task status to `processing`
6. Return A2A response with updated task state

#### 4.3 x-resume Handler

```python
def resume_handler(payload: dict) -> dict:
    # 1. Get task ID from headers
    with open(f"{MSG_ROOT}/headers/x-asya-resume-task") as f:
        task_id = f.read().strip()

    # 2. Load persisted message from storage
    persisted = load_message(task_id)  # From S3 via state proxy

    # 3. Load pause metadata to know where to merge fields
    pause_meta = persisted.get("_pause_metadata", {})
    fields = pause_meta.get("fields", [])

    # 4. Merge user input into restored payload
    restored_payload = persisted["payload"]
    for field in fields:
        name = field["name"]
        if name in payload:
            payload_key = field.get("payload_key", f"/{name}")
            set_at_path(restored_payload, payload_key, payload[name])

    # If no field mappings, merge at root (external pause / arbitrary input)
    if not fields:
        restored_payload.update(payload)

    # 5. Restore the route (continue from where we paused)
    restored_route = persisted["route"]
    # curr was "x-resume", next had remaining actors
    # Write the remaining route to VFS
    with open(f"{MSG_ROOT}/route/next", "w") as f:
        f.write("\n".join(restored_route["next"]))

    return restored_payload
```

After x-resume returns, the runtime shifts the route and the sidecar routes to the next actor (e.g., `summarizer`).

---

### 5. External Pause (User-Initiated)

#### 5.1 Pause Endpoint

```
POST /a2a/tasks/{id}:pause
```

Or via JSON-RPC: `tasks/pause` method.

1. Gateway marks task as `paused`
2. No pause metadata (no prompt/fields — user initiated the pause)
3. Sidecar discovers on next `GET /tasks/{id}/active` check that the task is inactive
4. Sidecar acks current message, does not route further

**Note**: The message may already be in-flight. If the handler has already returned and the sidecar is about to route, the sidecar checks `/tasks/{id}/active` before sending to the next queue. If inactive, the sidecar should persist the response to enable future resume.

#### 5.2 External Resume

Same as section 4.1-4.2, but since there's no field mapping, user input merges at payload root:

```python
# In x-resume: no fields defined, merge at root
if not fields:
    restored_payload.update(payload)
```

#### 5.3 Cancel Endpoint

```
POST /a2a/tasks/{id}:cancel
```

Or via JSON-RPC: `tasks/cancel` method.

1. Validate task is not in terminal state (`succeeded`, `failed`, `canceled`)
2. Mark task as `canceled`
3. Notify SSE subscribers
4. Sidecar discovers on next `/tasks/{id}/active` check

Cancel is a terminal state — canceled tasks cannot be resumed.

---

### 6. Timeout Interaction

> See also: RFC [[1crv]] (Timeouts Per-Actor and Per-Flow)

#### 6.1 Problem

The timeout system (RFC 1crv) uses absolute `deadline_at` timestamps on messages.
When a task is paused for human input (potentially hours/days), the original deadline
would expire, and every downstream sidecar would reject the message on resume.

#### 6.2 Industry Survey

| Framework | Timeout During Pause | Behavior |
|-----------|---------------------|----------|
| **A2A Protocol** | No timeout fields | Tasks persist indefinitely in `input_required` |
| **LangGraph** | No timeout | `interrupt()` waits indefinitely |
| **Mastra** | No timeout | `suspend()` persists "minutes, hours, or days" |
| **Temporal.io** | Timeout continues | Considered a design flaw; docs recommend explicit timers instead |
| **Google ADK** | Connection timeout only | No session expiration for paused states |

**Consensus**: Frameworks persist state indefinitely. Timeout is application-level
business logic, not infrastructure-level enforcement.

#### 6.3 Design

**Paused tasks have no timeout.** The gateway cancels the backstop timer on pause
and starts a fresh one on resume. No "remaining time" tracking.

| Event | Gateway Backstop Timer | Message `deadline_at` |
|-------|----------------------|----------------------|
| Task created | Started (`timeout_sec`) | Stamped on message by gateway |
| Task paused | **Canceled** | Irrelevant (message persisted in S3) |
| Task resumed | **Fresh timer** (`timeout_sec` from tool config) | x-resume stamps new `deadline_at = now + timeout_sec` |
| Task canceled | Canceled | N/A |

**Gateway behavior on pause:**
1. Cancel backstop `time.AfterFunc` timer
2. Store `timeout_sec` from tool config (for restart on resume)
3. No deadline tracking — paused tasks live until explicitly resumed or canceled

**Gateway behavior on resume:**
1. Start fresh backstop timer with original `timeout_sec`
2. Include `timeout_sec` in resume message headers (e.g., `x-asya-resume-timeout`)
3. x-resume stamps new `deadline_at = now + timeout_sec` on the outbound message

**x-resume behavior:**
1. Read `x-asya-resume-timeout` header from resume message
2. Compute `deadline_at = now + timeout_sec`
3. Stamp new `status.deadline_at` on outbound message (replacing the expired original)

**Rationale**: A resumed task is effectively a new request from the SLA perspective.
The user took time to provide input — that time should not count against the
pipeline's processing budget.

**Optional pause expiration**: Applications that need auto-cancellation of stale
paused tasks should implement cleanup as business logic (e.g., a scheduled job
that cancels tasks paused longer than N hours). This is NOT enforced by the framework.

---

### 7. Persistence Layer

x-pause and x-resume use the same persistence backend as the checkpointer crew actor (task `debt/1k34nz`). Currently this is S3/MinIO via `src/asya-crew/asya_crew/message_persistence/s3.py`.

**S3 key structure for paused messages:**
```
paused/{timestamp}/{actor}/{message_id}.json
```

**Persisted document** contains the full message plus pause metadata:
```json
{
  "id": "msg-uuid",
  "route": {"prev": ["analyzer", "x-pause"], "curr": "x-resume", "next": ["summarizer"]},
  "headers": {},
  "payload": {"analysis": "...", "score": 0.85},
  "_pause_metadata": {
    "prompt": "Review analysis",
    "fields": [{"name": "approved", "type": "boolean", "payload_key": "/approved"}]
  }
}
```

**Future**: When state proxy connectors mature, persistence will go through the state proxy abstraction layer, making the backend (S3, Postgres, Redis, NATS KV) configurable per deployment.

---

### 8. Database Changes (Gateway)

#### Migration 008

```sql
-- Store pause metadata for paused tasks
ALTER TABLE tasks ADD COLUMN pause_metadata JSONB;
```

The `pause_metadata` column stores the `x-pause` header content (prompt, fields) for clients to render appropriate input UI.

#### TaskStore Interface Additions

```go
// List retrieves tasks with optional filtering
List(ctx context.Context, filters TaskListFilters) (*TaskListResult, error)

// Cancel transitions a task to canceled state
Cancel(id string) error
```

---

### 9. Implementation Phases

#### Phase A: Gateway State Machine (A2A Phase 2 PR)

Scope: gateway + sidecar phase constants. No crew actors.

| Item | Component | Description |
|------|-----------|-------------|
| List tasks | Gateway | `GET /a2a/tasks` + `tasks/list` JSON-RPC |
| Cancel | Gateway | `POST /a2a/tasks/{id}:cancel` + `tasks/cancel` JSON-RPC |
| Paused/canceled phases | Sidecar | `PhasePaused`, `PhaseCanceled` constants |
| Pause header handling | Sidecar | Read `x-pause` header, report `paused` to gateway, stop routing |
| Pause state | Gateway | Accept `paused` phase, store metadata, SSE notification |
| Resume endpoint | Gateway | Accept `message/send` with `task_id` on paused task, queue to x-resume |
| External pause | Gateway | `POST /a2a/tasks/{id}:pause` endpoint |
| DB migration | Gateway | Migration 008: `pause_metadata` column |

#### Phase B: Crew Actors (separate PR)

| Item | Component | Description |
|------|-----------|-------------|
| x-pause | Crew | Persist message + set `x-pause` header |
| x-resume | Crew | Load persisted message, merge user input, continue route |
| Helm chart | Crew | Add x-pause and x-resume to asya-crew chart |
| Tests | Integration | Pause/resume flow end-to-end |

#### Phase C: Dynamic Exposure (future epic)

| Item | Component | Description |
|------|-----------|-------------|
| Dynamic tool registration | Gateway | x-pause tells gateway to register resume tool with input schema |
| Typed resume params | Gateway | Validate resume input against pause schema |
| Flow DSL integration | Compiler | `pause()` keyword in flow DSL |

---

### 10. Open Questions

1. **Sidecar persistence on external pause**: When sidecar discovers the task is paused mid-routing, should it persist the in-flight message before stopping? Without persistence, external-paused tasks cannot be resumed with full state.

2. **Multiple pause points**: Can a route have multiple x-pause/x-resume pairs? If so, each pause point persists the current state, and each resume loads from the most recent checkpoint.

3. **Pause metadata evolution**: When epic [[1ixz.typed-handler-signatures]] lands, the `fields` schema in `x-asya-pause` could be auto-generated from x-resume's handler signature. This would close the loop on dynamic tool exposure.

4. **Pause expiration policy**: Paused tasks have no framework-level timeout (section 6.3). Applications that need auto-cancellation should implement it as business logic (e.g., scheduled cleanup job). Should the framework provide a hook or convenience mechanism for this?
