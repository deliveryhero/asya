# Asya Runtime

Lightweight Unix socket server for actor processing logic.

> 📄 **Source Code**: [`src/asya-runtime/`](/src/asya-runtime/)
> 📖 **Developer README**: [`src/asya-runtime/README.md`](/src/asya-runtime/README.md)

## Overview

The runtime is a single Python script (`asya_runtime.py`) designed to be injected into AI model containers via ConfigMap. It handles communication between the actor sidecar and your Python application.

## Responsibilities

- Listen on a Unix socket for requests from the sidecar
- Dynamically load your process function from a module
- Handle errors gracefully with proper categorization
- Enforce message size limits to prevent OOM

## Usage

### Standalone (Testing)

```bash
python asya_runtime.py
```

### With Custom Process Function

Set the `ASYA_PROCESS_MODULE` environment variable:

```bash
# Format: module.path:function_name
export ASYA_PROCESS_MODULE="my_app.handler:process"
python asya_runtime.py

# Or just module.path (defaults to "process" function)
export ASYA_PROCESS_MODULE="my_app.handler"
python asya_runtime.py
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ASYA_SOCKET_PATH` | `/tmp/sockets/app.sock` | Path to Unix socket |
| `ASYA_PROCESS_MODULE` | _(none)_ | Python module with process function |
| `ASYA_MAX_MESSAGE_SIZE` | `10485760` (10MB) | Maximum message size in bytes |

## Process Function Contract

Your process function must follow this signature:

```python
def process(payload: dict) -> dict:
    """
    Process a payload and return a result.

    Args:
        payload: Dict containing the data to process

    Returns:
        Dict with the processing result
        OR
        List[Dict] for fan-out pattern

    Raises:
        ValueError: For validation errors (returned as validation_error)
        Any other exception is caught and returned as processing_error
    """
    # Your logic here
    return {"result": "processed"}
```

### Single Response Example

```python
# my_app/handler.py
def process(payload):
    if "text" not in payload:
        raise ValueError("Missing required field: text")

    # Process the text
    result = my_model.process(payload["text"])

    return {
        "processed_text": result,
        "model": "my-model-v1"
    }
```

### Fan-Out Example

```python
def process(payload):
    """Split text into chunks and return multiple messages"""
    text = payload["text"]
    chunks = split_into_chunks(text, size=100)

    # Return array for fan-out
    return [
        {"chunk_id": i, "text": chunk}
        for i, chunk in enumerate(chunks)
    ]
```

## Response Format

### Success
```json
{
  "status": "ok",
  "result": {...}  // or [...]
}
```

### Errors
```json
{
  "error": "error_type",
  "message": "error description",
  "type": "ExceptionClass"  // only for processing_error
}
```

**Error Types:**
- `validation_error`: ValueError raised by process function
- `processing_error`: Unexpected exception in process function
- `message_too_large`: Message exceeds size limit
- `empty_message`: No data received
- `invalid_json`: Failed to parse JSON
- `invalid_encoding`: Failed to decode UTF-8
- `connection_error`: Connection handling failed
- `server_error`: Failed to send response
- `out_of_memory`: Server ran out of memory

## Deployment

### Kubernetes Injection via ConfigMap

Create ConfigMap:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: asya-runtime
data:
  asya_runtime.py: |
    # (full content of asya_runtime.py)
```

Mount in pod:
```yaml
volumeMounts:
  - name: runtime
    mountPath: /app/asya_runtime.py
    subPath: asya_runtime.py
volumes:
  - name: runtime
    configMap:
      name: asya-runtime
```

Entrypoint:
```bash
# Start runtime in background
python /app/asya_runtime.py &

# Start your main application
python your_app.py
```

### Using Asya Operator

The operator can automatically configure the runtime when you specify it in your `Asya` resource:

```yaml
apiVersion: asya.io/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  workload:
    template:
      spec:
        containers:
        - name: runtime
          image: my-actor:latest
          env:
          - name: ASYA_PROCESS_MODULE
            value: "my_app.handler:process"
          - name: ASYA_SOCKET_PATH
            value: "/tmp/sockets/app.sock"
```

## Testing

```bash
# Run unit tests (requires uv)
cd src/asya-runtime
uv run pytest tests/ -v
```

## Complete Example

```python
# my_ai_app/inference.py
import torch
from transformers import AutoModel, AutoTokenizer

model = AutoModel.from_pretrained("bert-base-uncased")
tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")

def process(payload):
    """Run inference on text"""
    if "text" not in payload:
        raise ValueError("Missing 'text' field")

    text = payload["text"]

    # Tokenize and run inference
    inputs = tokenizer(text, return_tensors="pt")
    outputs = model(**inputs)

    return {
        "embeddings": outputs.last_hidden_state.tolist(),
        "model": "bert-base-uncased",
        "tokens": len(inputs["input_ids"][0])
    }
```

```bash
# Run the runtime
export ASYA_PROCESS_MODULE="my_ai_app.inference:process"
python asya_runtime.py
```

## Best Practices

1. **Keep process function stateless**: Each invocation should be independent
2. **Validate inputs early**: Use ValueError for validation errors
3. **Set appropriate timeout**: Configure `ASYA_RUNTIME_TIMEOUT` in sidecar based on processing time
4. **Handle cleanup**: Runtime restarts on critical errors, ensure proper cleanup
5. **Monitor memory**: Large models may need increased `ASYA_MAX_MESSAGE_SIZE`

## Next Steps

- [Sidecar Component](sidecar.md) - Message routing
- [Gateway Component](gateway.md) - Job management
- [Development Guide](../guides/development.md) - Local development
