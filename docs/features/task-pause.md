# Task Pause/Resume

Pause a pipeline mid-execution to collect human input, then resume with that
input merged into the payload. Designed for human-in-the-loop agentic workflows
where approval, clarification, or additional data is needed before continuing.

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

## Route Configuration

Place `x-pause` in the route where a pause point is needed. The handler
automatically prepends `x-resume` to `route.next` if missing, so explicitly
including it is optional but recommended for clarity:

```yaml
# Gateway tool definition
- name: review_pipeline
  description: Analyze data then pause for human review
  route: [analyzer, x-pause, summarizer]
  timeout: 120
```

A route can contain multiple pause points:

```yaml
route: [step-1, x-pause, step-2, x-pause, step-3]
```

Each pause persists the current state. On resume, the pipeline continues from
the most recent pause point.

## Pause Metadata

Pause metadata describes what input the pause point expects. It is passed to the
gateway and made available to clients so they can render appropriate input UI.

Configure via the `ASYA_PAUSE_METADATA` environment variable on the x-pause
actor:

```json
{
  "prompt": "Review this analysis before proceeding",
  "fields": [
    {
      "name": "approved",
      "type": "boolean",
      "prompt": "Approve this analysis?"
    },
    {
      "name": "notes",
      "type": "string",
      "prompt": "Any reviewer notes?",
      "payload_key": "/review/notes"
    }
  ]
}
```

### Field Properties

| Property | Required | Default | Description |
|----------|----------|---------|-------------|
| `name` | Yes | - | Field identifier (key in resume input) |
| `type` | Yes | - | JSON type: `string`, `boolean`, `number`, `array`, `object` |
| `prompt` | No | - | Human-readable label for UI |
| `payload_key` | No | `/<name>` | `/`-separated path where value lands in restored payload |
| `required` | No | `true` | UI hint; not enforced by x-resume (planned) |
| `default` | No | `null` | UI hint; not applied by x-resume (planned) |
| `options` | No | - | Enumerated choices for multichoice inputs |

When `payload_key` is omitted, the value merges at `payload["<name>"]`. When
specified, intermediate dicts are created automatically (e.g.,
`/review/notes` creates `payload["review"]["notes"]`).

When no fields are defined, resume input merges at the payload root via
shallow dict update.

## Resuming a Paused Task

Send an A2A `message/send` request with the `taskId` of the paused task:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "skill": "review_pipeline",
    "taskId": "<task-id>",
    "message": {
      "role": "user",
      "parts": [
        {"type": "data", "data": {"approved": true, "notes": "Looks good"}}
      ]
    }
  }
}
```

The gateway validates the task is paused, extracts the data from the message
parts, and queues it to x-resume.

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

## Helm Chart Configuration

Enable x-pause and x-resume in the `asya-crew` chart:

```yaml
x-pause:
  enabled: true
  transport: sqs  # must match your transport
  env:
    ASYA_PERSISTENCE_MOUNT: "/state"
    ASYA_PAUSE_METADATA: '{"prompt": "Approval needed", "fields": []}'

x-resume:
  enabled: true
  transport: sqs
  env:
    ASYA_PERSISTENCE_MOUNT: "/state"
    ASYA_RESUME_MERGE_MODE: "shallow"  # or "deep"
```

Both actors require `ASYA_PERSISTENCE_MOUNT` pointing to a shared storage mount
(S3/MinIO via state proxy connector). The mount path must be the same for both
so x-resume can read what x-pause wrote.

### Environment Variables

| Variable | Actor | Required | Description |
|----------|-------|----------|-------------|
| `ASYA_PERSISTENCE_MOUNT` | Both | Yes | State proxy mount path for paused message storage |
| `ASYA_PAUSE_METADATA` | x-pause | No | JSON pause metadata (prompt + fields schema) |
| `ASYA_RESUME_MERGE_MODE` | x-resume | No | `shallow` (default) or `deep` merge of user input |

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
