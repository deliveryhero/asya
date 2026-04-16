---
description: "Tutorial: build an echo actor, deploy to Kubernetes, send a message, verify the result"
---

# First Actor

## What you'll learn

- What an actor is and how it processes messages
- How to write a handler function
- How to deploy an actor to a Kubernetes cluster
- How to send a message and verify the result

## Prerequisites

- A running Asya playground cluster (follow the [Getting Started guide](../setup/start-quickstart.md) through step 4)
- `kubectl` configured to access your cluster

## Step 1: Write a handler

An actor handler is a plain Python function. It receives a `dict` payload, does some work, and returns a `dict`. No imports, no decorators, no framework dependencies.

Create a file called `echo_handler.py`:

```python
# echo_handler.py
async def process(payload: dict) -> dict:
    message = payload.get("message", "")
    return {
        **payload,
        "echo": message,
        "length": len(message),
    }
```

This handler reads a `message` field from the payload, echoes it back, and adds the message length. The `**payload` spread preserves any fields that upstream actors may have added -- this is the payload enrichment pattern.

## Step 2: Test your handler locally

Before deploying, verify the handler works as a plain function:

```python
from echo_handler import process

result = await process({"message": "hello world"})
assert result == {"message": "hello world", "echo": "hello world", "length": 11}
print("Handler works:", result)
```

No infrastructure needed -- it is just Python.

## Step 3: Package the handler in a Docker image

Create a `Dockerfile`:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY echo_handler.py /app/
```

Build and load it into your Kind cluster:

```bash
docker build -t echo-actor:v1 .
kind load docker-image echo-actor:v1 --name asya-quickstart
```

## Step 4: Deploy the AsyncActor

Create a file called `echo-actor.yaml`:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: echo
  namespace: asya-demo
spec:
  actor: echo
  image: echo-actor:v1
  handler: echo_handler.process
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
```

Key fields:

- `actor` -- the logical name used for queue naming and message routing
- `image` -- your Docker image containing the handler code
- `handler` -- the Python import path to your function (`module.function`)

Apply it:

```bash
kubectl apply -f echo-actor.yaml
```

Verify the actor was created:

```bash
kubectl get asyncactors -n asya-demo
```

You should see `echo` in the list. Asya automatically creates an SQS queue, a Deployment with the sidecar injected, and a KEDA ScaledObject.

## Step 5: Send a test message

Send a message to the actor's queue. The queue name follows the pattern `asya-{namespace}-{actor}`:

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-demo \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack-sqs.asya-demo:4566 \
      --queue-url http://localstack-sqs.asya-demo:4566/000000000000/asya-asya-demo-echo \
      --message-body '{\"id\":\"test-echo-1\",\"route\":{\"prev\":[],\"curr\":\"echo\",\"next\":[]},\"headers\":{},\"payload\":{\"message\":\"hello from Asya\"}}'
  "
```

The message body is an envelope -- it carries both the payload and the route. Since `route.next` is empty, the result will be routed to `x-sink` after processing.

## Step 6: Watch the actor process the message

KEDA detects the message in the queue and scales the echo deployment from 0 to 1:

```bash
kubectl get deployment echo -n asya-demo -w
```

Wait until you see `1/1` under READY (this takes about 30 seconds for scale-from-zero).

## Step 7: Check the result

Inspect the runtime logs to see the handler output:

```bash
POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=echo -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo "$POD" -c asya-runtime --tail=20
```

Inspect the sidecar logs to see the routing (received from SQS, called runtime, forwarded to x-sink):

```bash
kubectl logs -n asya-demo "$POD" -c asya-sidecar --tail=20
```

The sidecar logs should show the message being received, processed, and routed to x-sink. The result envelope now contains `{"echo": "hello from Asya", "length": 15}` in its payload.

## Step 8: Verify at x-sink

The x-sink actor persists completed results. Check its logs to confirm your message arrived:

```bash
SINK_POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=x-sink -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo "$SINK_POD" -c asya-runtime --tail=10
```

You should see the enriched payload with both `echo` and `length` fields.

## Clean up

Delete the actor when done:

```bash
kubectl delete asyncactor echo -n asya-demo
```

This cascades to the SQS queue, Deployment, and ScaledObject.

## What you built

You deployed a single actor that:

1. Received a message from an SQS queue
2. Executed your Python handler (via the runtime container)
3. Routed the result to x-sink (via the sidecar container)

The handler saw only `payload: dict -> dict`. Queue polling, routing, autoscaling, and result persistence were handled by the sidecar and crew actors.

## Next steps

- [Build Your First Pipeline](start-first-actor-mesh.md) -- chain multiple actors together
- [Handler Patterns](guide-handler-patterns.md) -- class handlers, error handling, advanced patterns
- [ABI Protocol Reference](../reference/specs/abi-protocol.md) -- understand envelopes, routing, metadata access
