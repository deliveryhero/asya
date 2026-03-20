<!-- Type: How-to -->

# How to Set Up Pause/Resume

Practical steps for configuring pause/resume in your actor pipelines,
including route configuration, pause metadata schema, Helm chart setup,
and resuming paused tasks.

For the full lifecycle explanation, sequence diagrams, timeout behavior,
and design rationale, see [Task Pause/Resume](../features/task-pause.md).

---

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

## Helm Chart Configuration

Enable x-pause and x-resume in the `asya-crew` chart:

```yaml
x-pause:
  enabled: true
  env:
    ASYA_PERSISTENCE_MOUNT: "/state"
    ASYA_PAUSE_METADATA: '{"prompt": "Approval needed", "fields": []}'

x-resume:
  enabled: true
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

---

## See also

- [Task Pause/Resume](../features/task-pause.md) — lifecycle explanation,
  sequence diagrams, timeout behavior, A2A state mapping, external pause/cancel
