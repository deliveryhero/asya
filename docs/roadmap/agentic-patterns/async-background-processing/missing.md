# Async Background Processing: Missing Functionality

## P0 — Blocking

### 1. No blocking mode for MCP tools/call

**Current state**: MCP `tools/call` dispatches to queue and returns task
metadata immediately. MCP clients (Claude Code, Goose) expect synchronous
tool results. They have no built-in mechanism to poll or subscribe to a
separate stream endpoint.

**Files**:
- `src/asya-gateway/internal/mcp/handlers.go:84-139` — returns
  `{task_id, stream_url}` not final result
- A2A has blocking wait (`blocking.go`) but MCP does not

**What's needed**:
- MCP tools/call with `_meta.blocking: true` (or similar): hold HTTP
  connection until pipeline completes, then return result inline
- Reuse A2A's `waitAndRelayEvents()` pattern for MCP
- Timeout: configurable per tool, default to tool's `timeout_sec`
- This is THE most critical gap for MCP agent integration. Without it, every
  MCP client needs custom streaming logic.

### 2. Pause metadata not in A2A status events (same as a2a-integration)

External agents can't determine what input is required when a background
task pauses. See `agent-a2a-integration/missing.md#1`.

---

## P1 — Important

### 3. No multi-stream subscription

**Current state**: Each task has its own SSE endpoint. Agents tracking N
concurrent pipelines need N separate SSE connections.

**Files**:
- `src/asya-gateway/internal/mcp/handlers.go` — `/stream/{id}` is per-task

**What's needed**:
- Multiplexed stream: `GET /stream?ids=task1,task2,task3`
- Each event tagged with source task_id
- Or: use A2A `tasks/resubscribe` with multiple task IDs (currently single)

### 4. No task grouping / batch tracking

**Current state**: No concept of a "batch" or "job" that groups multiple tasks.
An agent dispatching 10 analyses can't query "how many of my 10 tasks are done?"

**What's needed**:
- Batch ID parameter on task creation: `{batch_id: "q1-analysis"}`
- Batch status endpoint: `GET /a2a/?batch_id=q1-analysis`
  -> `{total: 10, completed: 7, failed: 1, running: 2}`
- Batch completion event when all tasks in batch finish

### 5. No estimated completion time

**Current state**: FLY events stream progress text but no structured ETA.
Agent can't tell the user "this will take approximately 5 more minutes."

**What's needed**:
- Pipeline step tracking: gateway knows step N of M from route metadata
- Historical step durations: "OCR typically takes 45s per document"
- ETA field in progress events: `{progress: 0.6, eta_seconds: 180}`

### 6. Backpressure drops FLY events silently

**Current state**: Subscriber channel buffer is 100. If the agent is slow to
consume SSE events (e.g., network latency), events are dropped with a warning
log. The agent misses progress updates.

**Files**:
- `src/asya-gateway/internal/store/store.go:256` — channel buffer size 100
- Drop logic: `select { case ch <- update: default: warn("dropped") }`

**What's needed**:
- Configurable buffer size per subscription
- Backpressure signal to upstream (slow down FLY emission)
- Or: buffer-and-flush with sequence numbers so client can detect gaps
- Event sequence numbers already designed but not implemented
  (see agentic umbrella ADR Section 12.1)

---

## P2 — Nice to Have

### 7. No task cancellation propagation to actors

**Current state**: A2A task cancellation marks the task as canceled in the
gateway DB. But the actor pods continue processing the envelope in the mesh.
Compute is wasted.

**Files**:
- `src/asya-gateway/internal/a2a/executor.go:Cancel()` — updates DB only
- No message sent to actor queue to signal cancellation

**What's needed**:
- Cancellation message sent to actor's queue with special header
- Sidecar detects cancellation header and stops processing
- Or: sidecar polls gateway for task status (heavyweight)

### 8. No resume without pause

**Current state**: An agent can only send additional input when a task is in
`input_required` state. Can't send "by the way, also check dataset X" to a
running task.

**What's needed**:
- "Steer" capability: agent sends supplementary context to running pipeline
- Actor receives steered input via sidecar-injected header
- This is the OpenClaw "steer" queue mode equivalent — fundamentally at odds
  with queue-based async model but useful for interactive scenarios
- Consider: out of scope for Asya's architecture (use pause/resume instead)
