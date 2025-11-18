# Quickstart for Data Scientists

Build and deploy your first Asya actor.

## Overview

As a data scientist, you focus on writing pure Python functions. Asya handles infrastructure, routing, scaling, and monitoring.

## Your Responsibility

Write a handler function or class:

```python
# handler.py
def process(payload: dict) -> dict:
    # Your logic here
    result = your_ml_model.predict(payload["input"])
    return {"result": result}
```

**That's it.** No infrastructure code, no decorators, no pip dependencies for queues/routing.

## Local Development

### 1. Write Handler

```python
# text_processor.py
def process(payload: dict) -> dict:
    text = payload.get("text", "")
    return {
        **payload,
        "processed": text.upper(),
        "length": len(text)
    }
```

### 2. Test Locally

```python
# test_handler.py
from text_processor import process

payload = {"text": "hello world"}
result = process(payload)
assert result == {
    "text": "hello world",
    "processed": "HELLO WORLD",
    "length": 11
}
```

**No infrastructure needed for testing**—pure Python functions.

### 3. Package in Docker

```dockerfile
FROM python:3.13-slim

WORKDIR /app
COPY text_processor.py /app/

# Install dependencies (if any)
# RUN pip install --no-cache-dir torch transformers

CMD ["python3", "-c", "import text_processor; print('Handler loaded')"]
```

```bash
docker build -t my-processor:v1 .
```

## Deployment

Platform team provides cluster access. You deploy AsyncActor CRD:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
spec:
  transport: sqs  # or rabbitmq (ask platform team)
  scaling:
    minReplicas: 0     # Scale to zero when idle
    maxReplicas: 50    # Max replicas
    queueLength: 5     # Messages per replica
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-processor:v1
          env:
          - name: ASYA_HANDLER
            value: "text_processor.process"  # module.function
```

```bash
kubectl apply -f text-processor.yaml
```

**Asya injects**:
- Sidecar for routing
- Entrypoint script for handler loading
- Autoscaling configuration
- Queue creation

## Using MCP Tools

If platform team deployed gateway, use `asya-mcp` tool:

```bash
# Install asya-cli
uv pip install -e ./src/asya-cli

# Set gateway URL (ask platform team)
export ASYA_CLI_MCP_URL=http://gateway-url/

# List available tools
asya-mcp list

# Call your actor
asya-mcp call text-processor --text="hello world"
```

Output:
```
[.] Envelope ID: abc-123
Processing: 100% |████████████████| , succeeded
{
  "result": {
    "text": "hello world",
    "processed": "HELLO WORLD",
    "length": 11
  }
}
```

## Advanced: Class Handlers

For stateful initialization (model loading):

```python
# ml_inference.py
class LLMInference:
    def __init__(self, model_path: str = "/models/default"):
        # Loaded once at startup
        self.model = load_llm(model_path)

    def process(self, payload: dict) -> dict:
        prompt = payload.get("prompt", "")
        response = self.model.generate(prompt)
        return {
            **payload,
            "response": response
        }
```

**Configuration**:
```yaml
env:
- name: ASYA_HANDLER
  value: "ml_inference.LLMInference.process"  # module.Class.method
- name: MODEL_PATH  # Passed to __init__
  value: "/models/llama3"
```

## Advanced: Fan-Out

Return list for fan-out (parallel processing):

```python
def process(payload: dict) -> list:
    chunks = payload["text"].split("\n")
    return [{"chunk": i, "text": chunk} for i, chunk in enumerate(chunks)]
```

**Result**: Sidecar creates multiple envelopes, sends each to next actor.

## Advanced: Dynamic Routing

Use envelope mode for runtime route modification:

```yaml
env:
- name: ASYA_HANDLER_MODE
  value: "envelope"  # Receive full envelope, not just payload
```

```python
def process(envelope: dict) -> dict:
    payload = envelope["payload"]

    # Add conditional routing
    if payload.get("priority") == "high":
        envelope["route"]["actors"].insert(
            envelope["route"]["current"] + 1,
            "priority-handler"
        )

    envelope["route"]["current"] += 1
    envelope["payload"]["processed"] = True
    return envelope
```

## Monitoring

```bash
# View actor status
kubectl get asya text-processor

# Watch autoscaling
kubectl get hpa -w

# View logs
kubectl logs -f deploy/text-processor

# View sidecar logs (routing, errors)
kubectl logs -f deploy/text-processor -c asya-sidecar
```

## Common Patterns

### Error Handling

```python
def process(payload: dict) -> dict:
    if "required_field" not in payload:
        raise ValueError("Missing required_field")

    # Process...
    return result
```

**Asya handles**:
- Catches exception
- Routes to `error-end` queue
- Reports to gateway

### Abort Pipeline

```python
def process(payload: dict):
    if payload.get("skip"):
        return None  # or []

    return {"processed": True}
```

**Result**: Envelope sent to `happy-end`, no further processing.

### Enrichment Pattern

```python
def process(payload: dict) -> dict:
    # Append results, don't replace
    return {
        **payload,
        "enrichment_from_this_actor": {...}
    }
```

**See**: [../architecture/protocols/actor-actor.md](../architecture/protocols/actor-actor.md#payload-enrichment-pattern)

## Next Steps

- Read [Core Concepts](../concepts.md)
- See [Architecture Overview](../architecture/)
- Explore [Example Actors](../../examples/)
