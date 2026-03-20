<!-- Type: Tutorial -->

# Add Human-in-the-Loop

## What you'll learn

- How to pause a pipeline for human input using `x-pause`
- The full pause/resume lifecycle
- How to resume a paused pipeline with new data
- How the gateway exposes paused tasks as `input_required`

## Prerequisites

- A running Asya playground cluster with the gateway installed (follow the [Getting Started guide](../quickstart/README.md) through step 4)
- Familiarity with actor pipelines (see [Build Your First Pipeline](first-pipeline.md))
- x-pause and x-resume crew actors enabled in your cluster

## The scenario

You will build a two-actor pipeline with a human approval step in the middle:

1. **draft** -- generates a report draft from the input
2. **x-pause** -- checkpoints the pipeline and waits for human review
3. **publish** -- finalizes the report with the human's feedback

The pipeline pauses after the draft is generated, waits for a human to review and approve, then continues to publish.

## Step 1: Write the handlers

Create `draft_handler.py`:

```python
# draft_handler.py
def process(payload: dict) -> dict:
    topic = payload.get("topic", "unknown")
    return {
        **payload,
        "draft": f"Draft report on: {topic}. Key findings: placeholder analysis.",
        "status": "awaiting_review",
    }
```

Create `publish_handler.py`:

```python
# publish_handler.py
def process(payload: dict) -> dict:
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

## Step 2: Build and load images

```dockerfile
# Dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY draft_handler.py /app/
COPY publish_handler.py /app/
```

```bash
docker build -t report-pipeline:v1 .
kind load docker-image report-pipeline:v1 --name asya-quickstart
```

## Step 3: Deploy the actors

Create `report-pipeline.yaml`:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: draft
  namespace: asya-demo
spec:
  actor: draft
  image: report-pipeline:v1
  handler: draft_handler.process
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: publish
  namespace: asya-demo
spec:
  actor: publish
  image: report-pipeline:v1
  handler: publish_handler.process
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
```

Apply:

```bash
kubectl apply -f report-pipeline.yaml
```

## Step 4: Understand the route

The route for this pipeline includes `x-pause` between draft and publish:

```
draft -> x-pause -> publish
```

When the message reaches `x-pause`:

1. x-pause persists the full envelope (payload + route + headers) to S3
2. x-pause signals `paused` to the sidecar via a special header
3. The sidecar reports `paused` status to the gateway and stops routing
4. The pipeline is frozen until a human resumes it

When the human sends a resume request:

1. The gateway queues a new message to `x-resume`
2. x-resume loads the persisted envelope from S3
3. x-resume merges the human's input into the restored payload
4. The pipeline continues from where it stopped (the `publish` actor)

## Step 5: Send a message with the pause route

The envelope's `route.next` includes `x-pause` followed by `publish`:

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-demo \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack-sqs.asya-demo:4566 \
      --queue-url http://localstack-sqs.asya-demo:4566/000000000000/asya-asya-demo-draft \
      --message-body '{\"id\":\"test-pause-1\",\"route\":{\"prev\":[],\"curr\":\"draft\",\"next\":[\"x-pause\",\"publish\"]},\"headers\":{},\"payload\":{\"topic\":\"Q3 performance review\"}}'
  "
```

## Step 6: Verify the pipeline paused

After the draft actor processes the message, it forwards to x-pause. Check the x-pause logs:

```bash
PAUSE_POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=x-pause -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo "$PAUSE_POD" -c asya-runtime --tail=10
```

You should see that x-pause persisted the envelope. The sidecar log confirms the `paused` status:

```bash
kubectl logs -n asya-demo "$PAUSE_POD" -c asya-sidecar --tail=10
```

At this point, the pipeline is frozen. The publish actor has not received any message. The persisted state includes the remaining route (`["publish"]`), so when resumed, the pipeline knows where to continue.

## Step 7: Resume with human input

If the gateway is installed, resume the pipeline by sending an A2A `message/send` request with the task ID. The gateway routes the human's input to `x-resume`, which loads the persisted state and merges the input.

Using the gateway's A2A endpoint:

```bash
curl -X POST http://localhost:8080/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "message/send",
    "params": {
      "taskId": "test-pause-1",
      "message": {
        "role": "user",
        "parts": [
          {
            "type": "data",
            "data": {
              "approved": true,
              "reviewer_notes": "Looks good, add a chart for Q3 metrics."
            }
          }
        ]
      }
    }
  }'
```

The gateway extracts the `data` part and queues it to x-resume. x-resume merges `approved` and `reviewer_notes` into the restored payload and forwards to the `publish` actor.

## Step 8: Verify the final result

Check the publish actor logs:

```bash
PUB_POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=publish -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo "$PUB_POD" -c asya-runtime --tail=10
```

Then verify at x-sink:

```bash
SINK_POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=x-sink -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo "$SINK_POD" -c asya-runtime --tail=10
```

The final payload should contain:

```json
{
  "topic": "Q3 performance review",
  "draft": "Draft report on: Q3 performance review. Key findings: placeholder analysis.",
  "approved": true,
  "reviewer_notes": "Looks good, add a chart for Q3 metrics.",
  "final_report": "Draft report on: Q3 performance review. Key findings: placeholder analysis.\n\nReviewer notes: Looks good, add a chart for Q3 metrics.",
  "status": "published"
}
```

## How the pause/resume lifecycle works

```
  Send message
       |
       v
  [draft] -- processes payload, enriches with draft
       |
       v
  [x-pause] -- persists envelope to S3, signals "paused"
       |
  (pipeline frozen)
       |
  Human reviews draft, sends resume with feedback
       |
       v
  [x-resume] -- loads persisted envelope, merges human input
       |
       v
  [publish] -- uses human feedback to finalize
       |
       v
  [x-sink] -- stores final result
```

Key points:

- x-pause and x-resume are built-in crew actors -- you do not write them
- The SLA timer freezes during the pause -- human think-time does not count
- A route can include multiple `x-pause` points for multi-step approval
- The gateway maps `paused` status to A2A `input_required` for client integrations

For the complete pause/resume specification, see [Task Pause/Resume](../features/task-pause.md).

## Clean up

```bash
kubectl delete asyncactor draft publish -n asya-demo
```

## What you built

You deployed a pipeline that:

1. Generates a draft report
2. Pauses for human review (checkpoint to S3)
3. Resumes with the reviewer's feedback merged into the payload
4. Publishes the final report

This pattern applies to any workflow that needs human approval: content moderation, expense approvals, deployment gates, or AI agent oversight.

## Next steps

- [Task Pause/Resume](../features/task-pause.md) -- pause metadata, field mappings, timeout behavior
- [ABI Protocol Reference](../reference/abi-protocol.md) -- dynamic routing from within handlers
- [Usage Guide](../quickstart/usage.md) -- class handlers, generator handlers, error handling
