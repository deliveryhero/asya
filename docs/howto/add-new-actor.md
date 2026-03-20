<!-- Type: How-to -->

# How to Add a New Actor

This guide walks through deploying a new actor to the Asya mesh: writing the
handler, creating the AsyncActor manifest, deploying, and verifying.

## Prerequisites

- A running Asya cluster with Crossplane and KEDA installed
- `kubectl` configured to reach the cluster
- A container image with your handler code (or a base Python image for inline handlers)

## Step 1: Write the handler

Every actor handler is a Python function with signature `dict -> dict`. The
function receives the envelope payload, processes it, and returns the
(possibly enriched) payload.

### Function handler (simplest)

```python
# file: handlers/echo.py

def process(payload: dict) -> dict:
    payload["greeting"] = f"Hello, {payload.get('name', 'world')}!"
    return payload
```

### Generator handler (for routing control or streaming)

Use a generator when you need to read envelope metadata, modify routing, or
stream tokens upstream.

```python
# file: handlers/router.py

async def process(payload: dict):
    # Read where the envelope came from
    prev = yield "GET", ".route.prev"

    # Conditionally re-route
    if payload.get("needs_review"):
        yield "SET", ".route.next", ["reviewer"]

    payload["processed"] = True
    yield payload
```

**Reference**: [ABI Protocol](../reference/abi-protocol.md) for the full verb
reference (GET, SET, DEL, FLY).

## Step 2: Build the container image

Package the handler into a container image. The handler file must be
importable by the Python runtime.

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY handlers/ /app/handlers/
# Install any dependencies your handler needs
# RUN pip install requests
```

```bash
docker build -t my-registry/echo-actor:v1 .
docker push my-registry/echo-actor:v1
```

If your handler has no dependencies beyond the standard library, you can use
`python:3.13-slim` directly as the image and mount the handler via a ConfigMap.

## Step 3: Create the AsyncActor manifest

Create a YAML manifest declaring the actor. Three fields are required:
`actor`, `image`, and `handler`.

```yaml
# file: echo-actor.yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: echo-actor
  namespace: my-project
spec:
  actor: echo-actor
  image: my-registry/echo-actor:v1
  handler: handlers.echo.process
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
```

**Key fields**:

| Field | Purpose |
|-------|---------|
| `spec.actor` | Logical identity; determines queue name (`asya-<namespace>-<actor>`) |
| `spec.image` | Container image containing your handler code |
| `spec.handler` | Python import path: `module.function` or `module.Class.method` |

**Reference**: [AsyncActor CRD Reference](../reference/asyncactor-crd.md) for
all available fields.

### Optional: configure autoscaling

```yaml
spec:
  scaling:
    enabled: true
    minReplicaCount: 0    # scale to zero when idle
    maxReplicaCount: 10
    queueLength: 5        # target messages per replica
```

### Optional: add environment variables

```yaml
spec:
  env:
  - name: MODEL_PATH
    value: "/models/my-model"
  - name: ASYA_LOG_LEVEL
    value: "DEBUG"
```

## Step 4: Deploy

```bash
kubectl apply -f echo-actor.yaml
```

Crossplane creates three resources:
1. A message queue (`asya-my-project-echo-actor`)
2. A Deployment (with sidecar and runtime containers)
3. A KEDA ScaledObject (if scaling is enabled)

## Step 5: Verify

### Check the actor status

```bash
kubectl get asyncactors -n my-project
```

Expected output:
```
NAME         ACTOR        STATUS   READY   REPLICAS   AGE
echo-actor   echo-actor   Ready    1       1          30s
```

### Check pod logs

```bash
# Runtime container logs (your handler)
kubectl logs -n my-project deployment/echo-actor -c asya-runtime

# Sidecar logs (queue polling, routing)
kubectl logs -n my-project deployment/echo-actor -c asya-sidecar
```

### Send a test envelope

If you have the gateway deployed, invoke the actor through an MCP tool or
send a message directly to the queue. To test the runtime directly:

```bash
kubectl exec -n my-project deployment/echo-actor -c asya-runtime -- \
  curl --unix-socket /var/run/asya/asya-runtime.sock \
  -X POST http://localhost/invoke \
  -H "Content-Type: application/json" \
  -d '{"id":"test-1","route":{"prev":[],"curr":"echo-actor","next":[]},"payload":{"name":"Asya"}}'
```

Expected response:
```json
{"frames":[{"payload":{"name":"Asya","greeting":"Hello, Asya!"},"route":{"prev":["echo-actor"],"curr":"","next":[]},"headers":{}}]}
```

### Check x-sink for results

After processing, successful envelopes arrive in the `x-sink` actor. Check its
logs for the final payload:

```bash
kubectl logs -n my-project deployment/x-sink -c asya-runtime
```

## Chaining actors into a pipeline

To create a multi-actor pipeline, deploy each actor separately and define the
route when sending the initial envelope. The route tells the sidecar where to
forward the envelope after each actor finishes.

Example: `preprocess -> inference -> postprocess`

1. Deploy all three actors (each with its own AsyncActor manifest)
2. Send an envelope with the full route:

```json
{
  "id": "pipeline-1",
  "route": {
    "prev": [],
    "curr": "preprocess",
    "next": ["inference", "postprocess"]
  },
  "payload": {"text": "Hello world"}
}
```

The sidecar advances the route automatically. When `postprocess` finishes with
an empty `route.next`, the envelope is routed to `x-sink`.

To register this pipeline as a gateway tool, see
[How to Register Tools in the Gateway](register-gateway-tools.md).

## Next steps

- [How to Debug an Envelope](debug-envelope.md) -- trace envelopes through the mesh
- [Understanding the Envelope](../explanation/envelope-design.md) -- why the envelope is designed this way
- [AsyncActor CRD Reference](../reference/asyncactor-crd.md) -- all spec fields
