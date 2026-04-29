---
description: "Pause/resume usage: yield SET to x-pause, handle resume input, human-in-the-loop workflow"
---

# Pause/Resume

How to pause your actor pipeline mid-execution to collect human input, then resume with that input merged into the payload.

## Overview

Asya provides two built-in crew actors for human-in-the-loop workflows:

- **x-pause** — checkpoints your pipeline and signals the gateway that human input is required
- **x-resume** — restores the checkpointed state, merges human input, and continues the pipeline

As an actor author, you control when and how pausing happens by:

1. Including `x-pause` in your route configuration
2. Optionally yielding dynamic routing to `x-pause` from within your handler
3. Designing your handler to process the merged input when the pipeline resumes

## Basic Pattern: Static Route

The simplest approach is to include `x-pause` in your route configuration.

### Example: Report Approval Workflow

```python
# draft_handler.py
async def process(payload: dict) -> dict:
    topic = payload.get("topic", "unknown")
    return {
        **payload,
        "draft": f"Draft report on: {topic}. Key findings: placeholder analysis.",
        "status": "awaiting_review",
    }
```

```python
# publish_handler.py
async def process(payload: dict) -> dict:
    draft = payload.get("draft", "")
    reviewer_notes = payload.get("reviewer_notes", "")
    approved = payload.get("approved", False)

    if approved:
        return {
            **payload,
            "final_report": f"{draft}\n\nReviewer notes: {reviewer_notes}",
            "status": "published",
        }
    return {
        **payload,
        "status": "rejected",
    }
```

**Route configuration:**

```
draft -> x-pause -> publish
```

When you send a message with this route:

```json
{
  "id": "report-123",
  "route": {
    "prev": [],
    "curr": "draft",
    "next": ["x-pause", "publish"]
  },
  "payload": {
    "topic": "Q3 performance review"
  }
}
```

The pipeline will:

1. Run `draft` — produces a draft report
2. Route to `x-pause` — persists the envelope to storage and signals `paused` to the gateway
3. Stop and wait for human input
4. When the human resumes with feedback, `x-resume` merges that feedback into the payload
5. Continue to `publish` — receives the original payload plus `approved` and `reviewer_notes`

## Dynamic Pause: Yielding SET

If you need conditional pausing based on runtime logic, use a generator handler with `yield "SET"` to rewrite the route.

### Example: Conditional Approval

```python
# draft_handler.py (generator version)
async def process(payload: dict):
    topic = payload.get("topic", "unknown")
    confidence = calculate_confidence(topic)

    draft = f"Draft report on: {topic}. Confidence: {confidence}%"

    result = {
        **payload,
        "draft": draft,
        "confidence": confidence,
        "status": "awaiting_review" if confidence < 90 else "auto_approved",
    }

    # Only pause if confidence is low
    if confidence < 90:
        yield "SET", ".route.next", ["x-pause", "publish"]
    else:
        yield "SET", ".route.next", ["publish"]

    yield result
```

In this example:

- High-confidence drafts skip human review and go straight to `publish`
- Low-confidence drafts insert `x-pause` dynamically and wait for human approval

## What Happens During Pause

When the envelope reaches `x-pause`:

1. **x-pause** persists the full envelope (payload, route, headers) to storage
2. **x-pause** ensures `x-resume` is the first actor in `route.next` (prepends if missing)
3. **x-pause** writes a special VFS header (`x-asya-pause`) and returns the payload
4. The **sidecar** detects the header and reports `paused` status to the gateway
5. The **gateway** freezes the SLA timer and transitions the task to `paused` (mapped to A2A `input_required`)
6. The pipeline stops — no further actors run until the human resumes

**Key point:** Human think-time does not count against your SLA budget. The timer freezes during the pause.

## Resume: Merging Human Input

When the human sends a resume request (via the gateway's A2A `message/send` endpoint), the gateway queues a new message to `x-resume` with the user's input as the payload.

**x-resume** then:

1. Loads the persisted envelope from storage
2. Merges the user's input into the restored payload (shallow merge at root level by default)
3. Restores the original `route.next` from before the pause (e.g., `["publish"]`)
4. Returns the merged payload

The pipeline continues from where it stopped.

### Resume Input Example

The human sends:

```json
{
  "approved": true,
  "reviewer_notes": "Looks good, add a chart for Q3 metrics."
}
```

**x-resume** merges this into the restored payload:

```json
{
  "topic": "Q3 performance review",
  "draft": "Draft report on: Q3 performance review. Key findings: placeholder analysis.",
  "status": "awaiting_review",
  "approved": true,
  "reviewer_notes": "Looks good, add a chart for Q3 metrics."
}
```

Your `publish` handler receives the merged payload and can now use `approved` and `reviewer_notes`.

## Designing Your Handler for Resume

When writing an actor that follows `x-pause`, structure your handler to handle both:

1. **Initial run** — the payload from the previous actor
2. **Resumed run** — the same payload plus the human's input fields

Use `.get()` with defaults to handle optional fields gracefully:

```python
async def process(payload: dict) -> dict:
    # Core data from the previous actor
    draft = payload.get("draft", "")

    # Optional human input (only present after resume)
    approved = payload.get("approved", False)
    reviewer_notes = payload.get("reviewer_notes", "")

    if approved:
        return {
            **payload,
            "final_report": f"{draft}\n\nReviewer notes: {reviewer_notes}",
            "status": "published",
        }
    return {
        **payload,
        "status": "rejected",
    }
```

## Multiple Pauses

A route can include multiple `x-pause` actors for multi-stage approval:

```
draft -> x-pause -> legal_review -> x-pause -> publish
```

Each pause:

- Checkpoints the state at that point
- Freezes the SLA timer
- Waits for a separate resume request

## Timeout Behavior

Example with a 30s SLA:

| Event | Elapsed | Remaining |
|-------|---------|-----------|
| Task created | 0s | 30s |
| Pause (after 10s processing) | 10s | 20s |
| Human reviews for 2 hours | - | 20s (frozen) |
| Resume | - | 20s |
| Second pause (after 5s more) | 15s | 15s |

The framework does not enforce a timeout on human think-time. If you need auto-cancellation of stale paused tasks, implement it as business logic (e.g., a scheduled cleanup job).

## Canceling Paused Tasks

Users can cancel a paused task via the gateway's A2A endpoint:

```
POST /a2a/tasks/{id}:cancel
```

Cancel is terminal — canceled tasks cannot be resumed.

## Common Patterns

### Approval Gate

```python
# approval_check.py (generator)
async def process(payload: dict):
    if needs_approval(payload):
        yield "SET", ".route.next", ["x-pause", "finalize"]
        yield {**payload, "status": "awaiting_approval"}
    else:
        yield "SET", ".route.next", ["finalize"]
        yield {**payload, "status": "auto_approved"}
```

### Data Collection

```python
# initial_draft.py
async def process(payload: dict) -> dict:
    return {
        **payload,
        "draft": generate_draft(payload),
        "missing_fields": ["customer_id", "due_date"],
    }

# finalize_with_user_data.py
async def process(payload: dict) -> dict:
    customer_id = payload.get("customer_id")
    due_date = payload.get("due_date")

    if not customer_id or not due_date:
        return {**payload, "status": "incomplete"}

    return {
        **payload,
        "final_output": finalize(payload),
        "status": "complete",
    }
```

Route: `initial_draft -> x-pause -> finalize_with_user_data`

The human provides `customer_id` and `due_date` during resume.

### Multi-Turn Agentic Loop

```python
# agent_step.py (generator)
async def process(payload: dict):
    conversation = payload.get("conversation", [])

    # Agent generates next response
    response = generate_response(conversation)
    conversation.append({"role": "assistant", "content": response})

    # If agent asks a question, pause for user input
    if requires_user_input(response):
        yield "SET", ".route.next", ["x-pause", "agent_step"]  # loop back to self
        yield {**payload, "conversation": conversation}
    else:
        # Task complete
        yield "SET", ".route.next", []
        yield {**payload, "conversation": conversation, "status": "complete"}
```

Route: `agent_step -> x-pause -> agent_step -> ...`

The actor loops back to itself after each pause, creating a multi-turn conversation.

---

**Platform setup**: To deploy and configure pause/resume infrastructure, see [setup/guide-pause-resume.md](../setup/guide-pause-resume.md).
