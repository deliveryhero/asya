<!-- Type: Explanation -->

# Task Pause/Resume

Pause a pipeline mid-execution to collect human input, then resume with that
input merged into the payload. Designed for human-in-the-loop agentic workflows
where approval, clarification, or additional data is needed before continuing.

For practical setup steps (route configuration, pause metadata schema, Helm
chart configuration, resuming tasks), see
[How to Set Up Pause/Resume](../howto/setup-pause-resume.md).

## How It Works

Two crew actors coordinate the pause/resume lifecycle:

- **x-pause** persists the full message to storage, writes the `x-asya-pause`
  VFS header, and returns the payload. The sidecar detects the header, reports
  `paused` to the gateway, and stops routing.
- **x-resume** loads the persisted message, merges the user's resume input into
  the restored payload, writes the remaining route back to VFS, and returns the
  merged payload. The pipeline continues from where it left off.

```
Client          Gateway         x-pause        Sidecar         x-resume       Next Actor
  |                |               |              |               |              |
  |-- call tool -->|               |              |               |              |
  |                |-- route msg ->|              |               |              |
  |                |               |-- persist -->|              |               |
  |                |               |-- set hdr -->|              |               |
  |                |               |<-- payload --|              |               |
  |                |               |              |-- paused --->|              |
  |                |<------------ paused ---------|              |               |
  |<-- paused -----|               |              |               |              |
  |                |               |              |               |              |
  |-- resume ----->|               |              |               |              |
  |                |-- queue to x-resume -------->|               |              |
  |                |               |              |               |-- load ----->|
  |                |               |              |               |-- merge ---->|
  |                |               |              |               |-- payload -->|
  |                |               |              |               |              |-- process
  |<------------ succeeded --------|--------------|---------------|--------------|
```

### Internal Flow

1. Pipeline routes message through actors until it reaches `x-pause`.
2. x-pause reads message metadata from VFS, ensures `x-resume` is first in
   `route.next` (prepends if missing), persists the full message as
   `{mount}/paused/{msg_id}.json`, and writes `x-asya-pause` header to VFS.
3. x-pause returns the payload. The runtime builds a response frame containing
   the VFS headers and sends it to the sidecar over the Unix socket.
4. Sidecar reads `x-asya-pause` from the response headers, reports
   `phase: paused` with pause metadata to the gateway, acks the message, and
   does **not** route to the next actor.
5. Gateway transitions the task to `paused`, stores pause metadata, freezes the
   SLA backstop timer, and notifies SSE subscribers with A2A state
   `input_required`.
6. Client sends a resume request (`message/send` with `taskId`). Gateway
   validates the task is paused, restarts the backstop timer with the remaining
   time budget, and queues a new message to `x-resume` with the user's input as
   payload and `x-asya-resume-task` header.
7. x-resume loads the persisted message, merges user input into the restored
   payload (using field mappings from pause metadata, or shallow merge at root
   if no fields defined), writes the restored `route.next` to VFS, and returns
   the merged payload.
8. Pipeline continues through remaining actors to completion.

## Timeout Behavior

Pause **freezes the SLA countdown**. Human think-time does not count against the
processing budget. On resume, the timer restarts with the remaining time.

Example with a 30s SLA:

| Event | Elapsed | Remaining |
|-------|---------|-----------|
| Task created | 0s | 30s |
| Pause (after 10s processing) | 10s | 20s |
| Human reviews for 2 hours | - | 20s (frozen) |
| Resume | - | 20s |
| Second pause (after 5s more) | 15s | 15s |

The framework does not enforce a timeout on human think-time. Applications
needing auto-cancellation of stale paused tasks should implement it as business
logic (e.g., a scheduled cleanup job).

## A2A State Mapping

| Task Status | A2A State | Description |
|-------------|-----------|-------------|
| `paused` | `input_required` | Waiting for human input |
| `canceled` | `canceled` | Terminal; cannot resume |

Clients polling task status or listening on SSE will see the A2A
`input_required` state, which signals that the task needs user interaction
before it can proceed.

## External Pause and Cancel

The gateway exposes endpoints for user-initiated pause and cancel:

```
POST /a2a/tasks/{id}:pause    # Pause a running task
POST /a2a/tasks/{id}:cancel   # Cancel a task (terminal)
```

**External pause** transitions the task to `paused` at the gateway level. The
endpoint accepts optional `metadata` in the request body for client context.
However, because x-pause never runs, no message state is persisted to storage.
This means externally paused tasks **cannot be resumed via x-resume** — resuming
requires a persisted state file that only x-pause creates. External pause is
currently useful for stopping a task and reporting `input_required` to clients,
but full resume support for externally paused tasks requires additional
implementation (e.g., sidecar-level persistence on pause discovery).

Cancel is terminal. Canceled tasks cannot be resumed.

---

## See also

- [How to Set Up Pause/Resume](../howto/setup-pause-resume.md) — route
  configuration, metadata schema, Helm setup, and resume request format
