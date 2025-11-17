# Onboarding Guide for Data Scientists

Guide for Data Scientists implementing processing logic in Asya🎭.

## What You'll Do

As a Data Scientist, you'll write **pure Python functions** that process data. No infrastructure code, no queue management, no deployment configs - just your ML/AI logic.

**Key idea**: Your handler function *mutates* the payload and returns it. Think data transformation pipeline, not request-response API.

## Prerequisites

**Development tools:**
- Python 3.7+ (or 3.13+ if using latest features)
- Your favorite IDE
- Basic understanding of Python functions and classes

**Optional:**
- Docker (for local testing with runtime)
- `uv` (Python package manager): `curl -LsSf https://astral.sh/uv/install.sh | sh`

**Project structure:**
- Handler functions in Python modules
- Handlers should be stateless or handle their own state
- No assumptions about execution order across pipeline steps

## Writing Your First Handler

### Simple Function Handler

The most basic handler is a pure function:

```python
# my_module.py
def process(payload: dict) -> dict:
    """
    Process a single payload.

    Args:
        payload: Input data from previous actor

    Returns:
        Processed result for next actor
    """
    # Your processing logic here
    result = your_ai_model.predict(payload["input"])

    # Return mutated payload
    return {
        **payload,  # Preserve input data
        "result": result  # Add your output
    }
```

**Configuration**: `ASYA_HANDLER=my_module.process`

### Class Handler (Recommended for AI Models)

For stateful processing (e.g., loading models), use class handlers:

```python
# my_module.py
class MyActor:
    def __init__(self, model_path: str = "/models/default"):
        """Initialize once when pod starts"""
        self.model = load_model(model_path)  # Load model once
        self.preprocessor = load_preprocessor()

    def process(self, payload: dict) -> dict:
        """Process each message"""
        # Preprocess
        data = self.preprocessor(payload["input"])

        # Run inference
        prediction = self.model.predict(data)

        # Return mutated payload
        return {
            **payload,
            "prediction": prediction,
            "confidence": float(prediction.confidence)
        }
```

**Configuration**: `ASYA_HANDLER=my_module.MyActor.process`

**Benefits**:
- Model loaded once during pod startup (not per message)
- Reuse preprocessing pipelines
- Maintain in-memory caches

## Handler Modes

### Payload Mode (Default, Recommended)

Handler receives only the payload. Framework manages routing automatically.

```python
def process(payload: dict) -> dict:
    # You only see the data
    return {"result": process_data(payload)}
```

**Use when**: You just want to process data without custom routing logic.

**Configuration**: `ASYA_HANDLER_MODE=payload` (default, can be omitted)

### Envelope Mode (Advanced)

Handler receives full envelope with route information. You can modify the pipeline dynamically.

```python
def process(envelope: dict) -> dict:
    """
    Envelope structure:
    {
        "id": "unique-id",
        "route": {
            "actors": ["step1", "step2", "step3"],
            "current": 0  # Which step we're at
        },
        "headers": {"trace_id": "..."},  # Optional metadata
        "payload": {...}  # Your data
    }
    """
    # Process payload
    payload = envelope["payload"]
    payload["result"] = process_data(payload)

    # Optional: Modify route dynamically
    route = envelope["route"]
    if payload["result"]["needs_review"]:
        route["actors"].append("human-review")  # Add extra step

    # Must preserve route history (actors[0:current+1])
    return envelope
```

**Use when**: You need dynamic routing based on processing results (e.g., LLM agents deciding next steps).

**Configuration**: `ASYA_HANDLER_MODE=envelope`

**Important rules**:
- You MUST preserve already-processed steps in `route.actors[0:current+1]`
- You CAN add future steps after `current+1`
- You CAN replace future steps
- Runtime will reject invalid route modifications

## Message Flow (What Happens to Your Code)

```
Queue → Sidecar → Your Handler → Sidecar → Next Queue
```

1. **Sidecar pulls** message from queue (e.g., `my-actor`)
2. **Sidecar calls** your handler via Unix socket
3. **Your code processes** and returns result
4. **Sidecar routes** result to next actor in pipeline
5. **Sidecar acknowledges** original message

**You never interact with queues directly** - the sidecar handles all infrastructure.

## Data Enrichment Pattern (Recommended)

Instead of overwriting data, **append** your results to the payload:

```python
# Input payload
{
    "product_id": "12345"
}

# Actor 1: data-loader
def process(payload: dict) -> dict:
    product = fetch_product(payload["product_id"])
    return {
        **payload,  # Keep product_id
        "product_name": product.name,
        "product_description": product.description
    }

# Actor 2: recipe-generator
def process(payload: dict) -> dict:
    recipe = generate_recipe(payload["product_description"])
    return {
        **payload,  # Keep all previous data
        "recipe": recipe
    }

# Actor 3: llm-judge
def process(payload: dict) -> dict:
    evaluation = evaluate_recipe(
        payload["product_name"],
        payload["recipe"]
    )
    return {
        **payload,  # Keep all previous data
        "recipe_eval": evaluation["verdict"],
        "recipe_eval_details": evaluation["reasoning"]
    }

# Final payload has all fields
{
    "product_id": "12345",
    "product_name": "Ice-cream Bourgignon",
    "product_description": "...",
    "recipe": "...",
    "recipe_eval": "VALID",
    "recipe_eval_details": "..."
}
```

**Benefits**:
- Each actor only needs specific fields (loose coupling)
- Full history available for debugging
- Easy to add/remove pipeline steps

## Error Handling

### Raising Errors

Just raise Python exceptions - the framework handles routing to error queue:

```python
def process(payload: dict) -> dict:
    if "required_field" not in payload:
        raise ValueError("Missing required_field")

    result = risky_operation(payload)
    if not result.success:
        raise RuntimeError(f"Operation failed: {result.error}")

    return {"result": result.data}
```

**What happens**:
- Exception raised → Runtime catches it
- Sidecar routes message to `error-end` queue
- `error-end` crew actor handles retry logic
- After max retries → Dead-letter queue

### Graceful Degradation

Handle errors gracefully when appropriate:

```python
def process(payload: dict) -> dict:
    try:
        result = external_api_call(payload["input"])
    except APIError:
        # Fallback to simpler method
        result = local_fallback(payload["input"])

    return {"result": result}
```

## Fan-out (Multiple Outputs)

Return a list to send multiple messages to the next actor:

```python
def process(payload: dict) -> list[dict]:
    """Split one message into many"""
    items = payload["batch_items"]

    # Return one result per item
    return [
        {"item_id": item["id"], "data": item}
        for item in items
    ]
```

**Use cases**:
- Batch processing (split batch into individual items)
- A/B testing (send to different downstream paths)
- Multi-model ensemble (send to multiple inference actors)

## Testing Your Handler

### Unit Testing (No Infrastructure)

Your handlers are pure functions - test them directly:

```python
# test_my_module.py
from my_module import MyActor

def test_process():
    actor = MyActor(model_path="/test/model")

    payload = {"input": "test data"}
    result = actor.process(payload)

    assert "prediction" in result
    assert result["confidence"] > 0.5
```

No Docker, no queues, no Kubernetes - just pure Python testing.

### Integration Testing (With Runtime)

Test with the actual runtime in Docker Compose:

```python
# See testing/component/ and testing/integration/ for examples
import json
import pika

# Send test message
envelope = {
    "id": "test-123",
    "route": {"actors": ["my-actor"], "current": 0},
    "payload": {"input": "test"}
}

channel.basic_publish(
    exchange='',
    routing_key='my-actor',
    body=json.dumps(envelope)
)

# Verify result from next queue
```

See [Testing Guide](../guides/testing.md) for complete examples.

## Common Gotchas

**Handler mode confusion:**
- `payload` mode (default): Handler only sees payload, sidecar manages routing
- `envelope` mode: Handler sees full envelope, must preserve route history
- **Use `payload` mode unless you need custom routing logic**

**State management:**
- Handlers should be stateless OR manage their own state
- No shared state between pod restarts
- Use class `__init__` for one-time setup (model loading)

**Dependencies:**
- Runtime has zero pip dependencies for infrastructure
- You can install your own ML libraries (torch, transformers, etc.)
- Add dependencies to your Dockerfile

**Return types:**
- Single dict → One output message
- List of dicts → Multiple output messages (fan-out)
- Must be JSON-serializable

**Automatic end routing:**
- Never add `happy-end` or `error-end` to routes
- Sidecar routes to them automatically
- When route completes → `happy-end`
- When error occurs → `error-end`

## Next Steps

- [Platform Engineer Onboarding](01-onboarding-platform.md) - How your code gets deployed
- [Core Concepts](02-concepts.md) - Deep dive into actors, envelopes, routing
- [Examples](../guides/examples-actors.md) - More handler patterns
- [Testing Guide](../guides/testing.md) - Complete testing strategies
