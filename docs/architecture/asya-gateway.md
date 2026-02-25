# Asya Gateway

## Responsibilities

- Expose MCP-compliant HTTP API
- Create tasks from HTTP requests
- Track task status in PostgreSQL
- Stream progress updates via Server-Sent Events (SSE)
- Receive status reports from crew actors

## How It Works

1. Client calls MCP tool via HTTP POST
2. Gateway creates task with unique ID
3. Gateway stores task in PostgreSQL (status: `pending`)
4. Gateway sends message to first actor's queue
5. Crew actors (`x-sink`, `x-sump`) report final task status
6. Client polls or streams task status updates via SSE

## Deployment

Deployed as separate Deployment in actor namespace:

```bash
helm install asya-gateway deploy/helm-charts/asya-gateway/ -f gateway-values.yaml
```

**Gateway is stateful**: Requires PostgreSQL database for task tracking.

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

Gateway exposes both **MCP-compliant** and **REST** endpoints.

### MCP Endpoints

**Standard MCP protocol** (recommended):
```bash
POST /mcp
# MCP request/response format
# Uses mark3labs/mcp-go server implementation
```

**Legacy SSE endpoint** (deprecated):
```bash
/mcp/sse
# Deprecated, use POST /mcp instead
```

### REST Endpoints

Simpler REST API for tool calls without MCP protocol overhead.

#### Call Tool (REST)

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

Response (MCP CallToolResult):
```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"task_id\":\"5e6fdb2d...\",\"message\":\"Task created successfully\",\"status_url\":\"/tasks/5e6fdb2d...\",\"stream_url\":\"/tasks/5e6fdb2d.../stream\"}"
    }
  ],
  "isError": false
}
```

See [Actor-Actor Protocol](protocols/actor-actor.md#task-status-tracking) for more details on task statuses.

#### Get Task Status

```bash
GET /tasks/{id}
```

Response:
```json
{
  "id": "5e6fdb2d-1d6b-4e91-baef-73e825434e7b",
  "status": "succeeded",
  "message": "Task completed successfully",
  "result": {"response": "Processed: Hello world"},
  "progress_percent": 100,
  "current_actor_idx": 2,
  "current_actor_name": "postprocess",
  "actors_completed": 3,
  "total_actors": 3,
  "created_at": "2025-11-18T12:00:00Z",
  "updated_at": "2025-11-18T12:01:30Z"
}
```

#### Stream Task Updates (SSE)

```bash
GET /tasks/{id}/stream
Accept: text/event-stream
```

**Features**:

- Sends historical updates first (no missed progress)
- Streams real-time updates as they occur
- Keepalive comments every 15 seconds
- Auto-closes on final status (`succeeded` or `failed`)

Stream events (TaskUpdate):
```
event: update
data: {"id":"task-123","status":"running","progress_percent":10,"current_actor_idx":0,"actor_state":"received","actor":"preprocess","actors":["preprocess","infer","post"],"message":"Actor preprocess: received","timestamp":"2025-11-18T12:00:15Z"}

event: update
data: {"id":"task-123","status":"running","progress_percent":33,"current_actor_idx":0,"actor_state":"completed","actor":"preprocess","actors":["preprocess","infer","post"],"message":"Actor preprocess: completed","timestamp":"2025-11-18T12:00:20Z"}

event: update
data: {"id":"task-123","status":"running","progress_percent":66,"current_actor_idx":1,"actor_state":"completed","actor":"infer","actors":["preprocess","infer","post"],"message":"Actor infer: completed","timestamp":"2025-11-18T12:01:00Z"}

event: update
data: {"id":"task-123","status":"succeeded","progress_percent":100,"result":{...},"message":"Task completed successfully","timestamp":"2025-11-18T12:01:30Z"}
```

**TaskUpdate fields**:

- `id`: Task ID
- `status`: Task status (`pending`, `running`, `succeeded`, `failed`)
- `progress_percent`: Progress 0-100 (omitted if not a progress update)
- `current_actor_idx`: Current actor index (0-based, omitted for final states)
- `actor_state`: Actor processing state (`received`, `processing`, `completed`)
- `actor`: Current actor name (omitted for final states)
- `actors`: Full route (may be modified via VFS)
- `message`: Human-readable status message
- `result`: Final result (only for `succeeded` status)
- `error`: Error message (only for `failed` status)
- `timestamp`: When this update occurred

#### Check Task Active

```bash
GET /tasks/{id}/active
```

**Used by**: Actors to verify task hasn't timed out

Response (active):
```json
{"active": true}
```

Response (inactive - HTTP 410 Gone):
```json
{"active": false}
```

### Internal Endpoints (Sidecar/Crew)

#### Report Progress

```bash
POST /tasks/{id}/progress
Content-Type: application/json

{
  "actors": ["prep", "infer", "post"],
  "current_actor_idx": 0,
  "status": "completed"
}
```

**Called by**: Sidecars at three points per actor (`received`, `processing`, `completed`)

**Progress formula**: `(actor_idx * 100 + status_weight) / total_actors`
- `received` = 10, `processing` = 50, `completed` = 100

Response:
```json
{"status": "ok", "progress_percent": 33.3}
```

#### Report Final Status

```bash
POST /tasks/{id}/final
Content-Type: application/json

{
  "id": "task-123",
  "status": "succeeded",
  "result": {...}
}
```

**Called by**: `x-sink` (success) or `x-sump` (failure) crew actors

#### Create Fanout Task

```bash
POST /tasks
Content-Type: application/json

{
  "id": "task-123-1",
  "parent_id": "task-123",
  "actors": ["prep", "infer"],
  "current": 1
}
```

**Called by**: Sidecars when runtime returns array (fan-out)

**Fanout ID semantics**:

- Index 0: Original ID (`task-123`)
- Index 1+: Suffixed (`task-123-1`, `task-123-2`)
- All children have `parent_id` for traceability

### Health Check

```bash
GET /health
```

Response: `OK`

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

## Using MCP tools
**See**: [For Data Scientists](../quickstart/for-data-scientists.md#using-mcp-tools) for instructions how to test MCP locally.

## Deployment Helm Charts

**See**: [../install/helm-charts.md](../install/helm-charts.md) for gateway chart details.
