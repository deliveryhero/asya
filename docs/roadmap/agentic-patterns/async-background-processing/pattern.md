# Async Background Processing (Agent + Asya Fire-and-Follow)

## Use-Case

A developer or AI agent dispatches a long-running task to Asya and continues
working on other things. The pipeline runs in the background on the company's
Kubernetes cluster. The agent receives progress updates via streaming and
gets notified when the task completes. Optionally, the agent can steer the
pipeline by sending additional context mid-execution (via pause/resume).

This is the "fire-and-follow" pattern — not fire-and-forget (which loses
observability) and not synchronous (which blocks the agent).

## Why Asya

- **Non-blocking dispatch**: A2A `message/send` returns immediately with
  `{task_id, status: "submitted"}`. The agent is free to continue.
- **FLY streaming**: Agent subscribes to `GET /stream/{task_id}` for
  real-time progress without holding a synchronous connection.
- **Durable execution**: Pipeline survives agent disconnection. Agent can
  reconnect and resume streaming via `tasks/resubscribe`.
- **Pause for steering**: If the pipeline reaches a decision point, it pauses.
  The agent detects `input_required`, prompts the user, and resumes with
  feedback.
- **Batch dispatch**: Agent can fire off multiple pipelines and track them
  independently. Each has its own task_id and stream.

## Architecture

```
Agent (Claude Code / Goose / custom)
  |
  |  1. POST /a2a/ message/send  (fire)
  |  2. GET /stream/{id}         (follow)
  |  3. Continue working...
  |  4. Receive completion event
  |
  v
Asya Gateway
  |
Actor Mesh (runs independently of agent)
```

## Interaction Flow

```
Agent                          Gateway                    Mesh
  |                               |                         |
  |-- message/send -------------->|                         |
  |<-- {task_id, submitted} ------|-- dispatch to queue --->|
  |                               |                         |
  |-- subscribe /stream/{id} ---->|                         |
  |                               |<-- FLY: "Processing..." |
  |<-- SSE: partial text ---------|                         |
  |                               |<-- FLY: "Step 2 of 5"  |
  |<-- SSE: progress -------------|                         |
  |                               |                         |
  | (agent continues other work)  |                         |
  |                               |<-- status: paused       |
  |<-- SSE: input_required -------|                         |
  |                               |                         |
  | (agent asks user) ----------> |                         |
  |-- message/send (resume) ----->|-- dispatch to x-resume  |
  |                               |                         |
  |                               |<-- FLY: "Finishing..."  |
  |<-- SSE: partial text ---------|                         |
  |                               |<-- status: completed    |
  |<-- SSE: completed ------------|                         |
```

## Example: Parallel Analysis Dispatch

```python
# Agent dispatches 3 analyses in parallel
tasks = []
for dataset in ["sales-q1", "sales-q2", "sales-q3"]:
    task = await a2a_client.send_message(
        message=f"Analyze {dataset} trends",
        metadata={"dataset": dataset}
    )
    tasks.append(task)

# Follow all 3 streams
async for task_id, event in a2a_client.subscribe_many([t.id for t in tasks]):
    if event.type == "artifact_update":
        print(f"[{task_id}] {event.content}")
    elif event.status == "completed":
        results[task_id] = event.result
```

## Key Properties

- **Agent independence**: Pipeline runs even if agent disconnects
- **Progress visibility**: FLY events provide real-time feedback
- **Steering capability**: Pause/resume for mid-pipeline decisions
- **Batch tracking**: Multiple concurrent pipelines, each independently tracked
- **Cost transparency**: Agent sees which steps ran and how long they took
