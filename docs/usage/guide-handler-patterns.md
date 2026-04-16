---
description: "Handler patterns: adapter pattern, generator vs function handlers, typed outputs, yield protocol"
---

# Handler Patterns

This guide covers practical patterns for writing Asya actor handlers: from basic
function handlers to advanced generator adapters, the adapter pattern for typed
domain code, and step-by-step deployment of new actors.

---

## Handler protocol: dict → dict

Every Asya actor handler speaks one protocol: `dict → dict`. Your handler
receives the envelope payload as a dictionary, processes it, and returns a
(possibly enriched) dictionary. That's the entire contract.

Two handler forms are supported:

1. **Function handler** — returns the payload directly
2. **Generator handler** — yields the payload and optionally uses the ABI protocol
   for routing control, metadata access, and streaming

Both forms can be sync or async. Both can be standalone functions or class
methods.

---

## Handler types

### Function handler

The simplest form: a function that takes a dict and returns a dict.

```python
# file: handlers/echo.py

async def process(payload: dict) -> dict:
    payload["greeting"] = f"Hello, {payload.get('name', 'world')}!"
    return payload
```

**When to use**: simple transformations that don't need routing control or
metadata access.

### Generator handler

Use a generator when you need to:
- Read envelope metadata (route, headers, ID)
- Modify routing dynamically (conditional routing, fan-out)
- Stream tokens upstream (FLY events for SSE clients)

```python
# file: handlers/router.py

async def process(payload: dict):
    # Read where the envelope came from
    prev = yield "GET", ".route.prev"

    # Conditionally re-route (prepend reviewer before remaining pipeline)
    if payload.get("needs_review"):
        yield "SET", ".route.next[:0]", ["reviewer"]

    payload["processed"] = True
    yield payload
```

**ABI verbs**: `GET`, `SET`, `DEL`, `FLY`. See [ABI Protocol Reference](../reference/specs/abi-protocol.md) for full details.

**When to use**: routing decisions, streaming, metadata inspection.

### Class-based handler

Use a class when your handler needs one-time initialization (model loading,
connection pooling).

```python
class InferenceActor:
    def __init__(self, model_path: str = "/models/default"):
        # __init__ is always synchronous — blocking I/O is fine here
        self.model = load_model(model_path)

    async def process(self, payload: dict) -> dict:
        result = await self.model.predict(payload["input"])
        payload["output"] = result
        return payload
```

Configure via `ASYA_HANDLER`:

```yaml
env:
  - name: ASYA_HANDLER
    value: "myapp.handlers.InferenceActor.process"
```

The runtime instantiates `InferenceActor()` once at startup. All `__init__`
parameters must have defaults.

---

## The adapter pattern

Your domain code often speaks something richer than `dict → dict` — typed models,
dataclasses, Pydantic schemas, or arbitrary function signatures. The **adapter
pattern** bridges the protocol and your domain types in plain Python, with no
framework magic.

### Why explicit adapters

The actor protocol is intentionally minimal. Every envelope carries a `payload`
dict and a `route`. Your handler receives the dict, transforms it, and returns
a dict. That's it.

Real domain code rarely looks like `dict → dict`. You might have:

```python
async def classify(text: str, threshold: float = 0.5) -> Label:
    ...
```

One option is to have the framework auto-extract fields and auto-merge results
via environment variables (`ASYA_PARAMS_AT=text`, `ASYA_RESULT_AT=label`).
That's implicit, hard to test, and couples your code to the platform's
conventions.

The alternative — and the approach Asya recommends — is to write a thin
**adapter function** that maps the protocol dict to your domain types and back:

```python
# Your domain function — clean, typed, testable
async def classify(text: str, threshold: float = 0.5) -> Label:
    ...

# The adapter — explicit protocol bridge
async def classify_actor(state: dict) -> dict:
    label = await classify(
        text=state["text"],
        threshold=state.get("threshold", 0.5),
    )
    state["label"] = label.value
    return state
```

You deploy `classify_actor` as the handler. The adapter is ~5 lines of plain
Python with no imports from Asya. You control the field names, the defaults,
and the merging strategy.

**Benefits**:

- **Transparent**: the mapping is explicit in code, not hidden in env vars
- **Testable**: call the adapter directly in pytest — no runtime needed
- **Flexible**: use any extraction/validation library you like (Pydantic,
  marshmallow, plain `dict.get`)
- **Evolvable**: when your domain function changes signature, the adapter shows
  exactly what breaks

---

## Function adapter

The simplest adapter: extract fields from the incoming dict, call your function,
merge the result back.

```python
# myapp/models.py
from dataclasses import dataclass

@dataclass
class Order:
    order_id: str
    amount: float
    currency: str = "USD"

@dataclass
class ProcessedOrder:
    order_id: str
    fee: float
    approved: bool
```

```python
# myapp/handlers.py
from myapp.models import Order, ProcessedOrder

# Domain function — no Asya dependency
async def process_order(order: Order) -> ProcessedOrder:
    fee = order.amount * 0.02
    return ProcessedOrder(
        order_id=order.order_id,
        fee=fee,
        approved=order.amount < 10_000,
    )

# Adapter — bridges dict protocol to domain types
async def process_order_actor(state: dict) -> dict:
    order = Order(
        order_id=state["order_id"],
        amount=state["amount"],
        currency=state.get("currency", "USD"),
    )
    result = await process_order(order)
    state["fee"] = result.fee
    state["approved"] = result.approved
    return state
```

The adapter does three things:

1. **Extract**: pull fields from `state` and construct the domain type
2. **Delegate**: call the domain function
3. **Merge**: write results back into `state` and return

Merging back into `state` (rather than returning a fresh dict) preserves all
upstream fields — trace IDs, metadata, and any context added by earlier actors.

### Extraction with validation

For stricter input validation, use Pydantic or dataclasses with `__post_init__`:

```python
from pydantic import BaseModel, validator

class OrderInput(BaseModel):
    order_id: str
    amount: float

    @validator("amount")
    def amount_positive(cls, v):
        if v <= 0:
            raise ValueError("amount must be positive")
        return v

async def process_order_actor(state: dict) -> dict:
    order_input = OrderInput(**state)   # raises ValidationError on bad input
    result = await process_order(order_input)
    state["fee"] = result.fee
    state["approved"] = result.approved
    return state
```

A `ValidationError` raised by Pydantic propagates as a handler exception. The
sidecar catches it, routes the envelope to `x-sump`, and reports the error to
the gateway.

---

## Generator adapter (streaming + ABI)

When your actor needs to stream tokens upstream, modify routing dynamically, or
read envelope metadata, use a **generator adapter**. The yield-based
[ABI protocol](../reference/specs/abi-protocol.md) provides four verbs: GET, SET,
DEL, FLY.

```python
# myapp/handlers.py
from myapp.llm import call_llm  # your domain function

async def llm_actor(state: dict):
    # Stream tokens upstream to connected SSE clients
    async for token in call_llm_stream(state["query"]):
        yield "FLY", {"type": "text_delta", "token": token}

    # Collect the full response
    response = await call_llm(
        query=state["query"],
        events=state.get("events", []),
    )

    # Append to the conversation history
    state.setdefault("events", []).append({
        "type": "model_response",
        "content": response.content,
        "tool_calls": response.tool_calls,
    })

    # Emit the updated state downstream
    yield state
```

The adapter pattern applies here too: `call_llm` and `call_llm_stream` are
ordinary async functions you can test and develop independently. The generator
adapter handles the protocol wrapping.

### Conditional routing

Read envelope metadata to decide where to send the result next:

```python
async def classifier_actor(state: dict):
    label = await classify(state["text"])
    state["label"] = label

    # Route based on classification result
    if label == "urgent":
        yield "SET", ".route.next", ["escalation-handler", "notifier"]
    else:
        yield "SET", ".route.next", ["standard-handler"]

    yield state
```

### Single-yield rule

A generator adapter should emit **exactly one downstream frame** for most use
cases. Multiple `yield <dict>` calls fan out into separate envelopes — one per
actor in the next queue. Use fan-out only when you intend to split work:

```python
# Fan-out: splits one envelope into N parallel envelopes
async def splitter_actor(state: dict):
    for item in state["items"]:
        yield {"item": item, "task_id": state["task_id"]}
```

---

## Class-based handler with adapter

Use a class handler when your actor needs one-time initialization — loading a
model, warming up a connection pool, or reading a configuration file. The
`__init__` runs once at startup; the handler method runs per message.

```python
# myapp/handlers.py
import torch
from myapp.model import InferenceModel

class InferenceActor:
    def __init__(self, model_path: str = "/models/default"):
        # __init__ is always synchronous — blocking I/O is fine here
        self.model = InferenceModel.load(model_path)
        self.model.eval()

    async def process(self, state: dict) -> dict:
        # Adapter: extract inputs
        inputs = torch.tensor(state["embeddings"])

        # Delegate to the model
        with torch.no_grad():
            logits = await self.model.predict(inputs)

        # Merge results back
        state["logits"] = logits.tolist()
        state["predicted_class"] = int(logits.argmax())
        return state
```

Configure via `ASYA_HANDLER`:

```yaml
env:
  - name: ASYA_HANDLER
    value: "myapp.handlers.InferenceActor.process"
```

The runtime instantiates `InferenceActor()` once with no arguments. All
`__init__` parameters must have defaults.

### Adapter inside a class

The same extraction-delegate-merge pattern applies inside the class method:

```python
class SentimentActor:
    def __init__(self, model_name: str = "distilbert-base-uncased"):
        from transformers import pipeline
        self.pipe = pipeline("sentiment-analysis", model=model_name)

    async def process(self, state: dict) -> dict:
        # Extract
        text = state["text"]

        # Delegate (transformers pipeline is sync — wrap in executor if needed)
        result = self.pipe(text)[0]

        # Merge
        state["sentiment"] = result["label"].lower()
        state["confidence"] = result["score"]
        return state
```

---

## Typed outputs and the JSON boundary

Asya actors communicate through JSON-serialized envelopes. A typed Python
object (pydantic model, dataclass) that one actor writes into `state` is
serialized to JSON before it reaches the next actor. The next actor's handler
receives a plain `dict`, not a typed object.

This shapes two rules:

**Rule 1: actors can store typed objects as outputs** — the runtime's
`_json_default` hook serializes them automatically. No `.model_dump()` or
`dataclasses.asdict()` needed in the adapter.

**Rule 2: incoming `state` values are always plain dicts** — treat every
value you read from `state` as a dict (or a primitive). Never use attribute
access on an incoming state value.

### Storing typed results (correct)

```python
from pydantic import BaseModel

class ScoredCandidate(BaseModel):
    text: str
    score: float

async def scorer(state: dict) -> dict:
    # Incoming value from previous actor — it's a list of dicts, not typed objects
    candidates = state["candidates"]

    # Domain function produces typed objects
    results = await score_all(state["query"], candidates)

    # Store typed results — the runtime serializes them on forward
    state["scores"] = results     # list[ScoredCandidate] → JSON automatically
    return state
```

### Reading incoming typed-looking values (correct)

```python
async def ranker(state: dict) -> dict:
    # state["scores"] is a list of plain dicts — it crossed a JSON boundary
    # Use ["key"] access, not attribute access
    scores = state["scores"]
    sorted_scores = sorted(scores, key=lambda s: s["score"], reverse=True)
    state["ranked"] = sorted_scores
    return state
```

### Reconstructing typed objects from incoming dicts

When your domain function requires typed inputs, reconstruct them inside the
adapter using `model_validate` or direct construction:

```python
async def ranker(state: dict) -> dict:
    # Reconstruct typed objects from the incoming dicts
    scores = [ScoredCandidate.model_validate(s) for s in state["scores"]]

    # Domain function works with typed inputs
    ranked = rank(scores)

    state["ranked"] = ranked     # ScoredCandidate list → JSON automatically
    return state
```

### The wrong pattern

```python
async def ranker(state: dict) -> dict:
    # WRONG: state["scores"][0] is a dict after crossing the JSON boundary
    for s in state["scores"]:
        print(s.score)           # AttributeError: 'dict' object has no attribute 'score'
```

### Summary of the boundary rule

| Location | Type of value | Access pattern |
|----------|--------------|----------------|
| Output from this actor | Any Python object | Store directly — runtime serializes |
| Input to this actor | Always `dict` / primitive | Use `["key"]` or `model_validate` |

---

## Testing adapters locally

Because adapters are plain Python functions, you test them with plain pytest —
no Asya runtime, no queues, no Docker.

### Testing function adapters

```python
# tests/test_handlers.py
import pytest
from myapp.handlers import process_order_actor

async def test_order_approved():
    state = {"order_id": "ord-001", "amount": 500.0}
    result = await process_order_actor(state)

    assert result["approved"] is True
    assert result["fee"] == pytest.approx(10.0)
    # Original fields are preserved
    assert result["order_id"] == "ord-001"

async def test_order_rejected_high_amount():
    state = {"order_id": "ord-002", "amount": 15_000.0}
    result = await process_order_actor(state)

    assert result["approved"] is False

async def test_invalid_input_raises():
    with pytest.raises(Exception):
        await process_order_actor({"amount": -1.0})  # missing order_id
```

### Testing generator adapters

The ABI reference provides an `actor()` helper that drives a generator and
returns the emitted payload. Copy it into a `conftest.py` or a test utility
module:

```python
# tests/conftest.py

async def actor(gen):
    """Drive a generator handler, return the single emitted frame."""
    frames = [e async for e in gen if isinstance(e, dict)]
    assert len(frames) == 1, f"Expected 1 frame, got {len(frames)}"
    return frames[0]
```

Use it to test generator adapters as if they were regular async functions:

```python
# tests/test_llm_actor.py
from unittest.mock import AsyncMock, patch
from myapp.handlers import llm_actor

async def test_llm_actor_appends_response(actor):
    state = {"query": "What is Asya?", "events": []}

    with patch("myapp.handlers.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value.content = "Asya is an actor mesh framework."
        mock_llm.return_value.tool_calls = []

        result = await actor(llm_actor(state))

    assert len(result["events"]) == 1
    assert result["events"][0]["content"] == "Asya is an actor mesh framework."
```

### Testing routing decisions

To verify that your adapter sets routing correctly, collect all yields instead
of filtering them:

```python
# tests/test_classifier_actor.py
from myapp.handlers import classifier_actor

async def collect(gen):
    return [e async for e in gen]

async def test_urgent_routing():
    state = {"text": "CRITICAL: system down"}

    with patch("myapp.handlers.classify", return_value="urgent"):
        events = await collect(classifier_actor(state))

    assert ("SET", ".route.next", ["escalation-handler", "notifier"]) in events

async def test_standard_routing():
    state = {"text": "Monthly report attached"}

    with patch("myapp.handlers.classify", return_value="normal"):
        events = await collect(classifier_actor(state))

    assert ("SET", ".route.next", ["standard-handler"]) in events
```

### Testing a multi-actor flow

Chain adapters together to test end-to-end behavior without any infrastructure:

```python
async def test_full_pipeline():
    state = {"order_id": "ord-100", "amount": 250.0, "text": "process order"}

    # Simulate each actor hop
    state = await process_order_actor(state)
    state = await actor(classifier_actor(state))

    assert state["approved"] is True
    assert "label" in state
```

Each `await` simulates a message hop through the actor mesh. In production,
each hop crosses a queue boundary between pods; in tests, they run sequentially
in one process. The behavior is identical because adapters are pure Python.

---

## Deploying a new actor

This section walks through the full lifecycle: writing the handler, packaging it,
creating the AsyncActor manifest, deploying, and verifying.

### Prerequisites

- A running Asya cluster with Crossplane and KEDA installed
- `kubectl` configured to reach the cluster
- A container image with your handler code (or a base Python image for inline handlers)

### Step 1: Build the container image

Package the handler into a container image. The handler file must be importable
by the Python runtime.

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

### Step 2: Create the AsyncActor manifest

Create a YAML manifest declaring the actor. Three fields are required: `actor`,
`image`, and `handler`.

```yaml
# file: asya-echo-actor.yaml
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

**Reference**: [AsyncActor CRD Reference](../reference/specs/asyncactor-crd.md) for all
available fields.

#### Optional: configure autoscaling

```yaml
spec:
  scaling:
    enabled: true
    minReplicaCount: 0    # scale to zero when idle
    maxReplicaCount: 10
    queueLength: 5        # target messages per replica
```

#### Optional: add environment variables

```yaml
spec:
  env:
  - name: MODEL_PATH
    value: "/models/my-model"
  - name: ASYA_LOG_LEVEL
    value: "DEBUG"
```

### Step 3: Deploy

```bash
kubectl apply -f asya-echo-actor.yaml
```

Crossplane creates three resources:
1. A message queue (`asya-my-project-echo-actor`)
2. A Deployment (with sidecar and runtime containers)
3. A KEDA ScaledObject (if scaling is enabled)

### Step 4: Verify

#### Check the actor status

```bash
kubectl get asyncactors -n my-project
```

Expected output:
```
NAME         ACTOR        STATUS   READY   REPLICAS   AGE
echo-actor   echo-actor   Ready    1       1          30s
```

#### Check pod logs

```bash
# Runtime container logs (your handler)
kubectl logs -n my-project deployment/echo-actor -c asya-runtime

# Sidecar logs (queue polling, routing)
kubectl logs -n my-project deployment/echo-actor -c asya-sidecar
```

#### Send a test envelope

If you have the gateway deployed, invoke the actor through an MCP tool or send a
message directly to the queue. To test the runtime directly:

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

#### Check x-sink for results

After processing, successful envelopes arrive in the `x-sink` actor. Check its
logs for the final payload:

```bash
kubectl logs -n my-project deployment/x-sink -c asya-runtime
```

### Chaining actors into a pipeline

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

The sidecar advances the route automatically. When `postprocess` finishes with an
empty `route.next`, the envelope is routed to `x-sink`.

To register this pipeline as a gateway tool, see [Gateway Setup Guide](../setup/guide-gateway.md).

---

## Summary

| Pattern | Use when |
|---------|----------|
| Function handler | Simple `dict → dict` transformation |
| Generator handler | Need streaming (FLY), routing control (SET), or metadata reads (GET) |
| Class handler | One-time initialization (model loading, connection pool) |
| Function adapter | Wrap typed domain functions in protocol handlers |
| Generator adapter | Wrap domain logic that needs ABI protocol features |
| Typed outputs | Store pydantic/dataclass results in state — runtime serializes automatically |
| Reconstruct on input | Use `Model.model_validate(state["field"])` when domain fn needs typed args |

The adapter is the thin boundary between the Asya protocol and your code. Keep it
small — ideally 5–15 lines — and put your real logic in the domain function it
wraps. That keeps your business logic framework-independent, testable anywhere
Python runs, and easy to understand.

---

## Further reading

- [ABI Protocol Reference](../reference/specs/abi-protocol.md) — full verb reference,
  path syntax, testing helpers
- [Runtime Component](../reference/components/core-runtime.md) — handler types, async
  support, configuration
- [Envelope Protocol](../reference/specs/envelope.md) —
  envelope structure and routing
- [How to Debug an Envelope](ops-debugging.md) — trace envelopes
  through the mesh
- [AsyncActor CRD Reference](../reference/specs/asyncactor-crd.md) — all spec fields
