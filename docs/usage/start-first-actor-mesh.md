
# Build Your First Pipeline

## What you'll learn

- How envelope routing chains actors together
- How `route.prev`, `route.curr`, and `route.next` change at each step
- How to deploy a multi-actor pipeline and trace a message through it

## Prerequisites

- A running Asya playground cluster (follow the [Getting Started guide](../quickstart/README.md) through step 4)
- Familiarity with single-actor deployment (see [Build Your First Actor](first-actor.md))

## The pipeline

You will build a two-actor pipeline:

1. **uppercaser** -- converts a text field to uppercase
2. **word-counter** -- counts the words in the uppercased text

Each actor enriches the payload and passes it along. The final result arrives at x-sink with contributions from both actors.

## Step 1: Write the handlers

Create `uppercaser.py`:

```python
# uppercaser.py
def process(payload: dict) -> dict:
    text = payload.get("text", "")
    return {
        **payload,
        "upper_text": text.upper(),
    }
```

Create `word_counter.py`:

```python
# word_counter.py
def process(payload: dict) -> dict:
    text = payload.get("upper_text", "")
    return {
        **payload,
        "word_count": len(text.split()),
    }
```

Test them together locally:

```python
from uppercaser import process as upper
from word_counter import process as count

payload = {"text": "hello actor mesh"}
payload = upper(payload)
payload = count(payload)
assert payload == {
    "text": "hello actor mesh",
    "upper_text": "HELLO ACTOR MESH",
    "word_count": 3,
}
```

## Step 2: Build and load images

Create a Dockerfile for each actor:

```dockerfile
# Dockerfile.uppercaser
FROM python:3.13-slim
WORKDIR /app
COPY uppercaser.py /app/
```

```dockerfile
# Dockerfile.word-counter
FROM python:3.13-slim
WORKDIR /app
COPY word_counter.py /app/
```

Build and load:

```bash
docker build -t uppercaser:v1 -f Dockerfile.uppercaser .
docker build -t word-counter:v1 -f Dockerfile.word-counter .
kind load docker-image uppercaser:v1 --name asya-quickstart
kind load docker-image word-counter:v1 --name asya-quickstart
```

## Step 3: Deploy both actors

Create `pipeline.yaml`:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: uppercaser
  namespace: asya-demo
spec:
  actor: uppercaser
  image: uppercaser:v1
  handler: uppercaser.process
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
  name: word-counter
  namespace: asya-demo
spec:
  actor: word-counter
  image: word-counter:v1
  handler: word_counter.process
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
kubectl apply -f pipeline.yaml
```

Verify both actors exist:

```bash
kubectl get asyncactors -n asya-demo
```

## Step 4: Understand the envelope route

Before sending a message, understand how the route drives the pipeline. The envelope you will send looks like this:

```json
{
  "id": "test-pipe-1",
  "route": {
    "prev": [],
    "curr": "uppercaser",
    "next": ["word-counter"]
  },
  "headers": {},
  "payload": {"text": "hello actor mesh"}
}
```

Here is what happens at each step:

**At uppercaser** (your message arrives here):

| Field | Value |
|-------|-------|
| `route.prev` | `[]` |
| `route.curr` | `"uppercaser"` |
| `route.next` | `["word-counter"]` |

The handler processes the payload. The runtime shifts the route: `curr` moves to `prev`, the first element of `next` becomes the new `curr`.

**At word-counter** (after uppercaser finishes):

| Field | Value |
|-------|-------|
| `route.prev` | `["uppercaser"]` |
| `route.curr` | `"word-counter"` |
| `route.next` | `[]` |

The handler processes the enriched payload. Since `route.next` is empty after shifting, the sidecar routes the result to x-sink.

**At x-sink** (terminal):

| Field | Value |
|-------|-------|
| `route.prev` | `["uppercaser", "word-counter"]` |
| `route.curr` | `""` |
| `route.next` | `[]` |

The final payload contains fields from both actors.

## Step 5: Send a message to start the pipeline

The message enters the pipeline at the first actor's queue. The `route.next` field lists the remaining actors:

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-demo \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack-sqs.asya-demo:4566 \
      --queue-url http://localstack-sqs.asya-demo:4566/000000000000/asya-asya-demo-uppercaser \
      --message-body '{\"id\":\"test-pipe-1\",\"route\":{\"prev\":[],\"curr\":\"uppercaser\",\"next\":[\"word-counter\"]},\"headers\":{},\"payload\":{\"text\":\"hello actor mesh\"}}'
  "
```

## Step 6: Trace the message through the pipeline

Watch both actors scale up:

```bash
kubectl get deployments -n asya-demo -w
```

After both actors have processed the message, check the logs. Start with uppercaser:

```bash
POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=uppercaser -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo "$POD" -c asya-sidecar --tail=10
```

The sidecar log should show the message being received from the uppercaser queue and forwarded to the word-counter queue.

Then check word-counter:

```bash
POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=word-counter -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo "$POD" -c asya-sidecar --tail=10
```

This sidecar should show the message arriving from uppercaser and being forwarded to x-sink.

## Step 7: Verify the final result at x-sink

```bash
SINK_POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=x-sink -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo "$SINK_POD" -c asya-runtime --tail=10
```

The final payload should contain all enrichments from both actors:

```json
{
  "text": "hello actor mesh",
  "upper_text": "HELLO ACTOR MESH",
  "word_count": 3
}
```

## Clean up

```bash
kubectl delete asyncactor uppercaser word-counter -n asya-demo
```

## What you built

You deployed a two-actor pipeline where:

1. The message route (`route.next`) defines the execution order
2. Each actor enriches the payload without knowing about the others
3. The sidecar handles all routing between queues
4. x-sink automatically receives the final result

The actors are independently deployable and scalable. Uppercaser could run 10 replicas while word-counter runs 2, and the pipeline would still work -- messages flow through queues, not direct calls.

## Next steps

- [Write Your First Flow](first-flow.md) -- use the Flow DSL to define pipelines in Python instead of manual routing
- [Add Human-in-the-Loop](pause-resume.md) -- pause a pipeline for human input
- [ABI Protocol Reference](../reference/abi-protocol.md) -- dynamic routing with generator handlers
