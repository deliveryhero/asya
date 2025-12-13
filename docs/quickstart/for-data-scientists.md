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

If platform team deployed the gateway, use `asya mcp` CLI tool:

```bash
# Install asya-cli
pip install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-cli

# Set gateway URL (ask platform team)
export ASYA_CLI_MCP_URL=http://gateway-url/

# List available tools
asya mcp list

# Call your actor
asya mcp call text-processor --text="hello world"
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

## Flow DSL: Simplified Pipeline Authoring

**Use case**: Define multi-actor pipelines in Python instead of manually managing routes and deployments.

The Flow DSL compiler transforms Python workflow descriptions into router-based actor networks, automating route management and deployment configuration.

### Writing a Flow

Flows are Python functions that describe how data flows through your pipeline:

```python
# text_analysis_flow.py
def text_analysis_flow(p: dict) -> dict:
    # Initialize metadata
    p["pipeline"] = "text_analysis"
    p["started_at"] = time.time()

    # Preprocessing
    p = clean_text(p)
    p = tokenize(p)

    # Conditional analysis
    if p["language"] == "en":
        p = english_sentiment(p)
    elif p["language"] == "es":
        p = spanish_sentiment(p)
    else:
        p["sentiment"] = "neutral"  # Skip analysis

    # Enrichment
    p = extract_entities(p)
    p["completed_at"] = time.time()

    return p

# Define your handler functions
def clean_text(p: dict) -> dict:
    return p

def tokenize(p: dict) -> dict:
    return p

def english_sentiment(p: dict) -> dict:
    return p

def spanish_sentiment(p: dict) -> dict:
    return p

def extract_entities(p: dict) -> dict:
    return p
```

**Key Features**:
- Write in familiar Python syntax
- Inline payload mutations (`p["key"] = value`)
- Conditional routing (`if`/`elif`/`else`)
- Early returns for validation
- Automatic router generation

### Compiling Flows

```bash
# Install asya-cli
pip install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-cli

# Compile flow
asya flow compile text_analysis_flow.py --output compiled/

# Generates:
# - compiled_routers.py (router actors)
# - plot.dot (flow diagram)
# - plot.png (visualization, requires graphviz)
```

### Deployment

Deploy generated routers and handler actors:

**1. Router Actors** (auto-generated):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: start-text-analysis-flow
spec:
  transport: sqs
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-routers:latest
          env:
          - name: ASYA_HANDLER
            value: "compiled_routers.start_text_analysis_flow"
          # Handler mappings
          - name: ASYA_HANDLER_CLEAN_TEXT
            value: "text_handlers.clean_text"
          - name: ASYA_HANDLER_TOKENIZE
            value: "text_handlers.tokenize"
          - name: ASYA_HANDLER_ENGLISH_SENTIMENT
            value: "sentiment.english_sentiment"
          - name: ASYA_HANDLER_SPANISH_SENTIMENT
            value: "sentiment.spanish_sentiment"
          - name: ASYA_HANDLER_EXTRACT_ENTITIES
            value: "nlp.extract_entities"
```

**2. Handler Actors** (your ML code):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: english-sentiment
spec:
  transport: sqs
  scaling:
    minReplicas: 0
    maxReplicas: 10
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-sentiment-model:latest
          env:
          - name: ASYA_HANDLER
            value: "sentiment.EnglishSentiment.process"
          resources:
            limits:
              nvidia.com/gpu: 1  # GPU for ML models
```

### Flow DSL Syntax Summary

**Supported**:
- Actor calls: `p = handler(p)`
- Payload mutations: `p["key"] = value`, `p["count"] += 1`
- Conditionals: `if`/`elif`/`else`, nested conditions
- Early returns: `if error: return p`
- Complex expressions: `p["result"] = p["x"] + p["y"] * 2`

**Not Supported** (use envelope mode instead):
- Loops (`for`, `while`)
- Custom routing logic
- Multiple assignments: `p, q = handler(p)`

### When to Use Flow DSL

✅ **Good for**:
- Linear pipelines with branching
- Data enrichment workflows
- Preprocessing → Model → Postprocessing patterns
- Validation and conditional processing

❌ **Not suitable for**:
- Dynamic routing based on runtime conditions
- Iterative processing (use loops in handlers)
- Complex control flow (use envelope mode)

### Example: ML Pipeline

```python
def ml_pipeline_flow(p: dict) -> dict:
    # Validation
    p = validate_input(p)
    if not p.get("valid", False):
        p["error"] = "Invalid input"
        return p  # Early exit

    # Preprocessing
    p["preprocessed"] = True
    p = normalize_data(p)
    p = extract_features(p)

    # Model selection
    if p["model_type"] == "fast":
        p = lightweight_model(p)
    elif p["model_type"] == "accurate":
        p = deep_model(p)
    else:
        p["error"] = "Unknown model type"
        return p

    # Postprocessing
    p = format_results(p)
    p["pipeline_complete"] = True

    return p
```

Compiles to:
- `start_ml_pipeline_flow` - Entry router with validation
- `router_ml_pipeline_flow_line_8_if` - Validation check router
- `router_ml_pipeline_flow_line_17_if` - Model selection router
- `end_ml_pipeline_flow` - Exit router

See [Flow Compiler Architecture](../architecture/asya-flow.md) for complete documentation.

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
2. Sidecar routes to `asya-{namespace}-error-end` queue
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
