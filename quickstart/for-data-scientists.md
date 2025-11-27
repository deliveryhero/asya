# Quickstart for Data Scientists

Build and deploy your first Asya actor.

## Overview

As a data scientist, you focus on writing pure Python functions. Asya handles infrastructure, routing, scaling, and monitoring.

**Core pattern**: Mutate and enrich the payload  -  not request/response. Each actor adds its results to the payload, which flows through the pipeline. See [payload enrichment pattern](../architecture/protocols/actor-actor.md#payload-enrichment-pattern) for more details.

Write a handler function or class:

```python
# handler.py
def process(payload: dict) -> dict:
    # Your logic here <...>
    result = your_ml_model.predict(payload["input"])

    # Recommendation: enrich payload, don't replace it
    return {
        **payload,            # Keep existing data
        "prediction": result  # Add your results
    }
```

**That's it.** No infrastructure code, no decorators, no pip dependencies for queues/routing.

## Mutating Payloads

**Pattern**: Each actor enriches the payload by adding its own fields. The enriched payload flows to the next actor.

### Function Handler

```python
# preprocessor.py
def process(payload: dict) -> dict:
    text = payload.get("text", "")
    return {
        **payload,  # Preserve input
        "cleaned_text": text.strip().lower(),
        "word_count": len(text.split())
    }
```

### Class Handler

Class handlers allow stateful initialization - perfect for loading models once at startup:

```python
# classifier.py
class TextClassifier:
    def __init__(self, model_path: str = "/models/default"):
        # Loaded once at pod startup, not per message
        self.model = load_model(model_path)
        print(f"Model loaded from {model_path}")

    def process(self, payload: dict) -> dict:
        text = payload.get("cleaned_text", "")
        prediction = self.model.predict(text)

        # Add classification results to payload
        return {
            **payload,  # Keep preprocessor results
            "category": prediction["category"],
            "confidence": prediction["score"]
        }
```

**IMPORTANT**: All `__init__` parameters must have default values:

```python
# ✅ Correct
def __init__(self, model_path: str = "/models/default"):
    ...

# ❌ Wrong - missing default
def __init__(self, model_path: str):
    ...
```

### Pipeline Flow Example

```python
# Actor 1: preprocessor
{"text": "Hello World"}
→ {"text": "Hello World", "cleaned_text": "hello world", "word_count": 2}

# Actor 2: classifier
{"text": "Hello World", "cleaned_text": "hello world", "word_count": 2}
→ {"text": "Hello World", "cleaned_text": "hello world", "word_count": 2, "category": "greeting", "confidence": 0.95}

# Actor 3: translator
{"text": "Hello World", ..., "category": "greeting", "confidence": 0.95}
→ {"text": "Hello World", ..., "category": "greeting", "confidence": 0.95, "translation": "Hola Mundo"}
```

Each actor adds its own fields, preserving all previous work.

### Fan-Out Pattern

Return a list to create multiple envelopes for parallel processing:

```python
def process(payload: dict) -> list:
    # Split text into chunks
    chunks = payload["text"].split("\n")

    # Each chunk becomes a separate envelope
    return [
        {**payload, "chunk_id": i, "chunk_text": chunk}
        for i, chunk in enumerate(chunks)
    ]
```

**Result**: Sidecar creates multiple envelopes (one per list item), routes each to the next actor in parallel.

### Abort Pattern

Return `None` or `[]` to stop pipeline execution:

```python
def process(payload: dict) -> dict | None:
    # Skip processing if already done
    if payload.get("already_processed"):
        return None  # Routes to happy-end, no further processing

    # Normal processing
    return {**payload, "result": "..."}
```

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

payload = {"text": "hello world", "request_id": "123"}
result = process(payload)
assert result == {
    "text": "hello world",
    "request_id": "123",  # Original data preserved
    "processed": "HELLO WORLD",
    "length": 11
}
```

**No infrastructure needed for testing** - pure Python functions.

### 3. Package in Docker

CI/CD is out of scope of Asya🎭 framework - ask your platform team for support.

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

Platform team provides cluster access. Your code will be deployed as `AsyncActor` CRD.

<details>
<summary>Click to see AsyncActor YAML (usually managed by platform team)</summary>

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: text-processor
spec:
  transport: sqs       # Ask platform team which transport is supported
  scaling:
    minReplicas: 0     # Scale to zero when idle
    maxReplicas: 50    # Max replicas
    queueLength: 5     # Messages per replica
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-processor:v1
          env:
          - name: ASYA_HANDLER
            value: "text_processor.process"  # module.function
          # For class handlers:
          # value: "text_processor.TextProcessor.process"  # module.Class.method
```

</details>

```bash
kubectl apply -f text-processor.yaml
```

**Asya automatically injects**:

- Sidecar for routing and transport
- Runtime entrypoint for handler loading
- Autoscaling configuration (KEDA)
- Queue creation (SQS/RabbitMQ)

## Using MCP Tools

If platform team deployed the gateway, use `asya-mcp` CLI tool:

```bash
# Install asya-cli
pip install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-cli

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

## Class Handler Examples

### LLM Inference

```python
# llm_inference.py
class LLMInference:
    def __init__(self, model_path: str = "/models/llama3"):
        # Load model once at startup
        self.model = load_llm(model_path)
        print(f"Loaded LLM from {model_path}")

    def process(self, payload: dict) -> dict:
        prompt = payload.get("prompt", "")
        response = self.model.generate(prompt, max_tokens=512)

        return {
            **payload,  # Keep all previous data
            "llm_response": response,
            "model": "llama3"
        }
```

**Deployment**:
```yaml
env:
- name: ASYA_HANDLER
  value: "llm_inference.LLMInference.process"
- name: MODEL_PATH
  value: "/models/llama3"  # Passed to __init__
```

### Image Classification

```python
# image_classifier.py
class ImageClassifier:
    def __init__(self, model_name: str = "resnet50"):
        import torchvision.models as models
        self.model = models.__dict__[model_name](pretrained=True)
        self.model.eval()

    def process(self, payload: dict) -> dict:
        image_url = payload.get("image_url")
        image = load_image(image_url)
        prediction = self.model(image)

        return {
            **payload,
            "predicted_class": prediction.argmax().item(),
            "confidence": prediction.max().item()
        }
```

**Deployment with GPU**:
```yaml
resources:
  limits:
    nvidia.com/gpu: 1
env:
- name: ASYA_HANDLER
  value: "image_classifier.ImageClassifier.process"
- name: MODEL_NAME
  value: "resnet50"
```

## Advanced: Envelope Mode (Dynamic Routing)

**Use case**: AI agents, LLM judges, conditional routing based on model outputs.

Envelope mode gives you full control over the routing structure:

```yaml
env:
- name: ASYA_HANDLER_MODE
  value: "envelope"  # Receive full envelope, not just payload
```

```python
# llm_judge.py
class LLMJudge:
    def __init__(self, threshold: float = 0.8):
        self.model = load_llm("/models/judge")
        self.threshold = float(threshold)

    def process(self, envelope: dict) -> dict:
        # Envelope structure:
        # {
        #   "id": "...",
        #   "payload": {...},  # Your data
        #   "route": {
        #     "actors": ["preprocessor", "llm-judge", "postprocessor"],
        #     "current": 1  # Points to current actor (llm-judge)
        #   }
        # }

        payload = envelope["payload"]

        # Run LLM judge
        score = self.model.judge(payload["llm_response"])
        payload["judge_score"] = score

        # Dynamically modify route based on score
        route = envelope["route"]
        if score < self.threshold:
            # Low quality response - add refinement step
            route["actors"].insert(
                route["current"] + 1,  # After current position
                "llm-refiner"  # Extra step
            )

        # Increment current pointer
        route["current"] += 1

        return envelope
```

**Important**: Route modification rules:

- ✅ Can add/replace future steps
- ✅ Can insert actors after current position
- ❌ Cannot modify already-processed steps
- ❌ Cannot change which actor `route.current` points to

## Error Handling

Asya automatically handles exceptions:

```python
def process(payload: dict) -> dict:
    if "required_field" not in payload:
        raise ValueError("Missing required_field")

    # Normal processing
    result = do_work(payload["required_field"])
    return {**payload, "result": result}
```

**When exception occurs**:
1. Runtime catches exception and creates error envelope with traceback
2. Sidecar routes to `asya-error-end` queue
3. Error-end actor persists error details to S3
4. Gateway receives final failure status

**No manual error handling needed** - framework handles everything.

## Monitoring

Your platform team will set up monitoring dashboards. For quick checks:

**Note**: More comprehensive monitoring capabilities (dashboards, alerts, metrics) are coming soon. Ask your platform team about current monitoring setup.

<details>
<summary>Advanced: kubectl commands (optional)</summary>

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

</details>

## Next Steps

- Read [Core Concepts](../concepts.md)
- See [Architecture Overview](../architecture/README.md)
- Explore [Example Actors](https://github.com/deliveryhero/asya/tree/main/examples)
- Learn about [Envelope Protocol](../architecture/protocols/actor-actor.md)
