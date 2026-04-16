---
description: "Tutorial: write a Flow DSL file, compile to actor graph, inspect generated routers, deploy"
---

# First Flow

## What you'll learn

- How the Flow DSL describes pipelines as Python functions
- How to compile a flow into router actors
- What the compiler generates and why
- How to deploy and run a compiled flow

## Prerequisites

- A running Asya playground cluster (follow the [Getting Started guide](../setup/start-quickstart.md) through step 4)
- Familiarity with actor pipelines (see [Build Your First Pipeline](start-first-actor-mesh.md))
- `asya-lab` installed: `pip install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-lab`

## Why flows?

In the [pipeline tutorial](start-first-actor-mesh.md), you set the route manually in the envelope:

```json
{"route": {"prev": [], "curr": "uppercaser", "next": ["word-counter"]}}
```

This works for linear chains, but becomes tedious when you need branching, loops, or conditional routing. The Flow DSL lets you describe the pipeline in Python, and the compiler generates the routing logic for you.

## Step 1: Write a flow

Create a file called `text_pipeline.py`:

```python
from asya_lab.flow import flow


@flow
async def text_pipeline(p: dict) -> dict:
    p = await normalize(p)
    p = await analyze(p)
    return p


async def normalize(p: dict) -> dict:
    """Lowercase and strip whitespace."""
    text = p.get("text", "")
    return {**p, "normalized": text.strip().lower()}


async def analyze(p: dict) -> dict:
    """Count characters and words."""
    text = p.get("normalized", "")
    return {
        **p,
        "char_count": len(text),
        "word_count": len(text.split()),
    }
```

The flow function (`text_pipeline`) describes the execution order: first `normalize`, then `analyze`. The handler functions below it are the actual actor implementations.

## Step 2: Compile the flow

Run the compiler:

```bash
asya flow compile text_pipeline.py --output-dir ./compiled/ --plot
```

Expected output:

```
[+] Successfully compiled flow to: compiled/routers.py
[+] Generated graphviz dot file: compiled/flow.dot
[+] Generated graphviz svg plot: compiled/flow.svg
```

## Step 3: Inspect the generated code

Open `compiled/routers.py`. You will see two router functions:

**`start_text_pipeline`** -- the entry point. It prepends the handler actors into `route.next`:

```python
async def start_text_pipeline(payload: dict):
    """Entrypoint for flow 'text_pipeline'"""
    _next = []
    _next.append(resolve("normalize"))
    _next.append(resolve("analyze"))
    yield "SET", ".route.next[:0]", _next
    yield payload
```

**`end_text_pipeline`** -- the exit point. It clears `route.next` so the message goes to x-sink:

```python
async def end_text_pipeline(payload: dict):
    """Exitpoint for flow 'text_pipeline'"""
    yield "SET", ".route.next", []
    yield payload
```

The routers use the ABI yield protocol (`yield "SET", ...`) to modify the envelope's routing. The `resolve()` function maps handler names to deployed actor names at runtime via environment variables.

If you used `--plot`, open `compiled/flow.svg` to see a visual diagram of the flow.

## Step 4: Build images

You need two images: one for the router actors and one for each handler actor. For this tutorial, you can put everything in one image for simplicity.

Create a `Dockerfile`:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY text_pipeline.py /app/
COPY compiled/routers.py /app/
```

Build and load:

```bash
docker build -t text-pipeline:v1 .
kind load docker-image text-pipeline:v1 --name asya-quickstart
```

## Step 5: Deploy the actors

Every function in the flow becomes a separate AsyncActor. Deploy the routers and handlers:

```yaml
# flow-actors.yaml

# Entry router
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: start-text-pipeline
  namespace: asya-demo
spec:
  actor: start-text-pipeline
  image: text-pipeline:v1
  handler: routers.start_text_pipeline
  env:
    - name: ASYA_HANDLER_NORMALIZE
      value: "text_pipeline.normalize"
    - name: ASYA_HANDLER_ANALYZE
      value: "text_pipeline.analyze"
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
---
# Handler: normalize
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: normalize
  namespace: asya-demo
spec:
  actor: normalize
  image: text-pipeline:v1
  handler: text_pipeline.normalize
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
---
# Handler: analyze
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: analyze
  namespace: asya-demo
spec:
  actor: analyze
  image: text-pipeline:v1
  handler: text_pipeline.analyze
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
```

The `ASYA_HANDLER_*` environment variables on the router tell `resolve()` how to map handler names to actor names. The variable name suffix (e.g., `NORMALIZE`) becomes the actor name in kebab-case (`normalize`).

Apply:

```bash
kubectl apply -f flow-actors.yaml
```

## Step 6: Send a message

Send a message to the start router. The router will set up the route for the full pipeline:

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-demo \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack-sqs.asya-demo:4566 \
      --queue-url http://localstack-sqs.asya-demo:4566/000000000000/asya-asya-demo-start-text-pipeline \
      --message-body '{\"id\":\"test-flow-1\",\"route\":{\"prev\":[],\"curr\":\"start-text-pipeline\",\"next\":[]},\"headers\":{},\"payload\":{\"text\":\"  Hello World  \"}}'
  "
```

## Step 7: Verify the result

After the actors scale up and process the message, check x-sink:

```bash
SINK_POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=x-sink -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo "$SINK_POD" -c asya-runtime --tail=10
```

The final payload should contain:

```json
{
  "text": "  Hello World  ",
  "normalized": "hello world",
  "char_count": 11,
  "word_count": 2
}
```

## How it works

Here is the message flow:

1. Message arrives at `start-text-pipeline` with empty `route.next`
2. The start router sets `route.next` to `["normalize", "analyze"]`
3. Sidecar forwards message to `normalize`
4. `normalize` processes the payload, sidecar forwards to `analyze`
5. `analyze` processes the payload, `route.next` is empty, sidecar forwards to x-sink

The Flow DSL compiler automated the routing setup. Without it, you would need to manually specify `route.next` in every envelope you send, as you did in the [pipeline tutorial](start-first-actor-mesh.md).

## Clean up

```bash
kubectl delete asyncactor start-text-pipeline normalize analyze -n asya-demo
```

## What you built

You used the Flow DSL to:

1. Describe a pipeline in familiar Python syntax
2. Compile it into router actors that handle envelope routing
3. Deploy the routers alongside your handler actors
4. Run the pipeline by sending a message to the entry point

The flow compiler transforms Python control flow into message-passing chains. For simple sequences, this saves a few lines of YAML. The real payoff comes with branching and loops -- see the [Flow DSL Reference](../reference/specs/flow-dsl.md) for the full syntax.

## Next steps

- [Add Human-in-the-Loop](../setup/guide-pause-resume.md) -- pause a pipeline for human approval
- [Flow DSL Reference](../reference/specs/flow-dsl.md) -- conditionals, loops, fan-out, error handling
- [ABI Protocol Reference](../reference/specs/abi-protocol.md) -- the yield protocol used by generated routers
