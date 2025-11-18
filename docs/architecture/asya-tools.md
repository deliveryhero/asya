# Asya Tools

CLI tools for interacting with Asya system.

## Installation

```bash
uv pip install -e ./src/asya-tools
```

## asya-mcp

CLI for interacting with MCP Gateway.

### List Tools

```bash
asya-mcp list
```

Output:
```
- name: text-processor
  description: Process text with LLM
  parameters:
    text:
      type: string
      required: true
```

### Call Tool

```bash
asya-mcp call text-processor --text="Hello world"
```

Output (with SSE streaming):
```
[.] Envelope ID: 5e6fdb2d-1d6b-4e91-baef-73e825434e7b
Processing: 100% |████████████████████████████████████| , succeeded
{
  "id": "5e6fdb2d-1d6b-4e91-baef-73e825434e7b",
  "status": "succeeded",
  "result": {
    "response": "Processed: Hello world"
  }
}
```

### Get Status

```bash
asya-mcp status 5e6fdb2d-1d6b-4e91-baef-73e825434e7b
```

### Configuration

Set gateway URL:
```bash
export ASYA_TOOL_MCP_URL=http://localhost:8089/
```

## asya-mcp-forward

Port-forwarding utility for local testing.

```bash
asya-mcp-forward
```

Automatically:
1. Port-forwards `asya-gateway` service to `localhost:8089`
2. Sets `ASYA_TOOL_MCP_URL` environment variable
3. Keeps port-forward alive until interrupted

**See**: `src/asya-tools/README.md` for advanced usage.
