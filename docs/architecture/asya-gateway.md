# Asya Gateway

## Responsibilities

- Expose MCP-compliant HTTP API
- Create envelopes from HTTP requests
- Track envelope status in PostgreSQL
- Stream progress updates via Server-Sent Events (SSE)
- Receive status reports from crew actors

## How It Works

1. Client calls MCP tool via HTTP POST
2. Gateway creates envelope with unique ID
3. Gateway stores envelope in PostgreSQL (status: `pending`)
4. Gateway sends envelope to first actor's queue
5. Crew actors (`happy-end`, `error-end`) report final status
6. Client polls or streams status updates via SSE

## Deployment

Deployed as separate Deployment in actor namespace:

```bash
helm install asya-gateway deploy/helm-charts/asya-gateway/ \
  -f gateway-values.yaml
```

**Gateway is stateful**: Requires PostgreSQL database for envelope tracking.

## Configuration

Configured via Helm values or config file:

```yaml
# gateway-values.yaml
config:
  sqsRegion: "us-east-1"
  postgresHost: "postgres.default.svc.cluster.local"
  postgresDatabase: "asya_gateway"
  postgresPasswordSecretRef:
    name: postgres-secret
    key: password
routes:
  tools:
  - name: text-processor
    description: Process text with LLM
    parameters:
      text:
        type: string
        required: true
      model:
        type: string
        default: "gpt-4"
    route: ["preprocess", "llm-infer", "postprocess"]
```

**See**: `src/asya-gateway/config/README.md` for complete config reference.

## API Endpoints

### List Tools

```bash
GET /tools
```

Response:
```json
{
  "tools": [
    {
      "name": "text-processor",
      "description": "Process text with LLM",
      "inputSchema": {
        "type": "object",
        "properties": {
          "text": {"type": "string"},
          "model": {"type": "string"}
        },
        "required": ["text"]
      }
    }
  ]
}
```

### Call Tool

```bash
POST /tools/call
Content-Type: application/json

{
  "name": "text-processor",
  "arguments": {
    "text": "Hello world",
    "model": "gpt-4"
  }
}
```

Response:
```json
{
  "envelope_id": "5e6fdb2d-1d6b-4e91-baef-73e825434e7b",
  "status": "pending"
}
```

### Get Status

```bash
GET /envelopes/{id}
```

Response:
```json
{
  "id": "5e6fdb2d-1d6b-4e91-baef-73e825434e7b",
  "status": "succeeded",
  "message": "Envelope completed successfully",
  "result": {
    "response": "Processed: Hello world"
  },
  "progress_percent": 100,
  "timestamp": "2025-11-18T12:00:00Z"
}
```

### Stream Status (SSE)

```bash
GET /envelopes/{id}/stream
Accept: text/event-stream
```

Stream events:
```
event: status
data: {"status": "processing", "progress_percent": 33, "message": "Actor preprocess completed"}

event: status
data: {"status": "processing", "progress_percent": 66, "message": "Actor llm-infer completed"}

event: status
data: {"status": "succeeded", "progress_percent": 100, "result": {...}}
```

## Tool Examples

**Simple tool**:
```yaml
- name: hello
  description: Say hello
  parameters:
    who:
      type: string
      required: true
  route: [hello-actor]
```

**Multi-step pipeline**:
```yaml
- name: image-enhance
  description: Enhance image quality
  parameters:
    image_url:
      type: string
      required: true
    quality:
      type: string
      enum: [low, medium, high]
      default: medium
  route: [download-image, enhance, upload]
```

**Complex parameters**:
```yaml
- name: llm-pipeline
  description: Multi-step LLM processing
  parameters:
    prompt:
      type: string
      required: true
    config:
      type: object
      properties:
        temperature:
          type: number
          default: 0.7
        max_tokens:
          type: integer
          default: 1000
  route: [validate, llm-infer, postprocess]
```

## Deployment Helm Charts

**See**: [../install/helm-charts.md](../install/helm-charts.md) for gateway chart details.
