<!-- Type: How-to -->

# How to Register Tools in the Gateway

This guide shows how to register actor pipelines as MCP tools and A2A skills
in the Asya gateway using ConfigMap-based configuration.

## Prerequisites

- The Asya gateway deployed (both `api` and `mesh` pods)
- One or more deployed AsyncActor resources
- `kubectl` access to the cluster

## How tool registration works

The gateway reads tool definitions from a ConfigMap named `gateway-flows`,
mounted into the api pod at `ASYA_CONFIG_PATH`. The gateway polls this
ConfigMap every 5 seconds and hot-reloads without a pod restart.

**Reference**: [Gateway Architecture](../architecture/asya-gateway.md) for the
full ConfigMap/PostgreSQL state ownership model.

## Step 1: Define a flow in flows.yaml

Each flow maps a name to an actor pipeline. Create a `flows.yaml` file (or
patch the existing ConfigMap directly).

### Single-actor tool

```yaml
flows:
- name: echo
  entrypoint: echo-actor
  description: Echo back the input with a greeting
  mcp:
    inputSchema:
      type: object
      properties:
        name:
          type: string
          description: Name to greet
      required: [name]
```

### Multi-actor pipeline

```yaml
flows:
- name: text-analysis
  entrypoint: preprocess
  route_next: [inference, postprocess]
  description: Analyze text through a preprocessing, inference, and postprocessing pipeline
  timeout: 120
  mcp:
    inputSchema:
      type: object
      properties:
        text:
          type: string
          description: Text to analyze
      required: [text]
```

### Expose as both MCP and A2A

Include both `mcp` and `a2a` sections:

```yaml
flows:
- name: text-analysis
  entrypoint: preprocess
  route_next: [inference, postprocess]
  description: Analyze text
  mcp:
    inputSchema:
      type: object
      properties:
        text:
          type: string
      required: [text]
  a2a: {}
```

### Flow configuration fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique flow name; becomes the MCP tool name and A2A skill name |
| `entrypoint` | yes | First actor in the pipeline (actor name, not queue name) |
| `route_next` | no | Ordered list of subsequent actors |
| `description` | no | Human-readable description surfaced in tool/skill listings |
| `timeout` | no | Max seconds to wait for completion |
| `mcp` | no | Present = exposed as MCP tool; requires `inputSchema` |
| `a2a` | no | Present = exposed as A2A skill |

## Step 2: Apply the ConfigMap

### Option A: Patch the existing ConfigMap

The Helm chart creates an empty `gateway-flows` ConfigMap. Patch it with your
flow definitions:

```bash
kubectl create configmap gateway-flows \
  -n asya-system \
  --from-file=flows.yaml=flows.yaml \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Option B: Use kubectl patch

```bash
kubectl patch configmap gateway-flows -n asya-system \
  --type merge \
  -p "$(cat <<'EOF'
data:
  flows.yaml: |
    flows:
    - name: echo
      entrypoint: echo-actor
      description: Echo handler
      mcp:
        inputSchema:
          type: object
          properties:
            name:
              type: string
          required: [name]
EOF
)"
```

### Option C: Include in Helm values

If you manage the gateway via Helm, add flows to your values file:

```yaml
# gateway-values.yaml
flows:
- name: echo
  entrypoint: echo-actor
  description: Echo handler
  mcp:
    inputSchema:
      type: object
      properties:
        name:
          type: string
      required: [name]
```

```bash
helm upgrade asya-gateway deploy/helm-charts/asya-gateway/ -f gateway-values.yaml
```

## Step 3: Verify registration

The gateway hot-reloads the ConfigMap within 5 seconds. No restart needed.

### Verify MCP tools

```bash
# List available tools via MCP
curl -X POST http://<gateway-api>/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Your tool should appear in the response:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "echo",
        "description": "Echo back the input with a greeting",
        "inputSchema": {
          "type": "object",
          "properties": {
            "name": {"type": "string", "description": "Name to greet"}
          },
          "required": ["name"]
        }
      }
    ]
  }
}
```

### Verify A2A skills

```bash
curl http://<gateway-api>/.well-known/agent.json | jq '.skills'
```

### Invoke a tool

```bash
curl -X POST http://<gateway-api>/tools/call \
  -H "Content-Type: application/json" \
  -d '{"name": "echo", "arguments": {"name": "Asya"}}'
```

Response:

```json
{
  "content": [{"type": "text", "text": "{\"task_id\":\"...\",\"status_url\":\"/mesh/...\"}"}],
  "isError": false
}
```

## Updating or removing tools

To update a tool, patch the ConfigMap with the new definition. The gateway
picks up the change within 5 seconds.

To remove a tool, remove its entry from `flows.yaml` and re-apply the
ConfigMap.

To force an immediate reload (instead of waiting for the poll interval):

```bash
curl -X POST http://<gateway-mesh>/mesh/config-reload
```

## Next steps

- [Gateway Architecture](../architecture/asya-gateway.md) -- deployment model, security, and state ownership
- [How to Add a New Actor](add-new-actor.md) -- deploy the actors your tools reference
