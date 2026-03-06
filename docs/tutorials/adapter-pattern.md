# The Adapter Pattern

Asya actors speak one protocol: `dict → dict`. Your domain code speaks something
richer — typed models, dataclasses, Pydantic schemas, or arbitrary function
signatures. The **adapter pattern** bridges the two in plain Python, with no
framework magic.

---

## Why explicit adapters

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
[ABI protocol](../reference/abi-protocol.md) provides four verbs: GET, SET,
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

## Summary

| Pattern | Use when |
|---------|----------|
| Function adapter | Simple `dict → dict` transformation with typed domain types |
| Generator adapter | Need streaming (FLY), routing control (SET), or metadata reads (GET) |
| Class adapter | One-time initialization (model loading, connection pool) |

The adapter is the thin boundary between the Asya protocol and your code.
Keep it small — ideally 5–15 lines — and put your real logic in the domain
function it wraps. That keeps your business logic framework-independent,
testable anywhere Python runs, and easy to understand.

---

## Further reading

- [ABI Protocol Reference](../reference/abi-protocol.md) — full verb reference,
  path syntax, testing helpers
- [Architecture: Runtime](../architecture/asya-runtime.md) — handler types,
  async support, configuration
- [Architecture: Actor Envelope](../architecture/protocols/actor-actor.md) —
  envelope structure and routing
