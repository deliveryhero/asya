# Asya🎭 CLI

Command-line developer tools for debugging and operating the Asya🎭 framework.

## Installation

```bash
cd src/asya-cli
uv pip install -e .
```

Or install directly from the repository:

```bash
uv pip install -e ./src/asya-cli
```

## Tools

### asya-mcp

Lightweight CLI for calling MCP tools on asya-gateway without AI integration.

#### Configuration

Set defaults via environment variables:

```bash
export ASYA_CLI_URL=http://localhost:8011
export ASYA_CLI_NO_STREAM=true      # Don't stream by default
export ASYA_CLI_DEBUG=true          # Enable debug mode by default
```

Or override per-command with flags:

```bash
asya-mcp --url http://gateway.example.com:8080 list
asya-mcp --no-stream call my_tool
asya-mcp --debug call my_tool
```

#### Usage

Global options (`--url`, `--no-stream`, `--debug`) go **before** the command.

```bash
# List available tools
asya-mcp list

# Show detailed tool configuration
asya-mcp show echo

# Call a tool with no arguments (uses defaults)
asya-mcp call my_tool

# Call a tool with JSON arguments (default: streams progress with SSE, shows tqdm bar)
asya-mcp call echo '{"message": "hello world"}'

# Call a tool with --param=value or --param value flags (easier syntax)
asya-mcp call echo --message="hello world"
asya-mcp call echo --message "hello world"
asya-mcp call process --count=10 --enabled=true
asya-mcp call test_timeout --sleep_seconds=5
asya-mcp call test_timeout --sleep_seconds 5

# Global options before command
asya-mcp --no-stream call long-running-task --input=data
asya-mcp --debug call test_progress --value 10
asya-mcp --url http://gateway.example.com:8080 list

# Check envelope status
asya-mcp status <envelope-id>

# Stream live updates for an envelope
asya-mcp stream <envelope-id>
```

Alternatively, use as a Python module:

```bash
python -m asya_cli.mcp list
```

**Call modes:**
- **Default** (no flags): Streams real-time SSE updates with tqdm progress bar (percentage + envelope state) → returns final result as JSON to stdout
- **`--no-stream`** or **`--no_stream`**: Returns envelope ID immediately without waiting. Use `status` or `stream` commands to check progress later.

**Environment Variables:**
- `ASYA_CLI_URL` - Default gateway URL (default: `http://localhost:8089`)
- `ASYA_CLI_NO_STREAM` - Set to `true`, `1`, or `yes` to disable streaming by default
- `ASYA_CLI_DEBUG` - Set to `true`, `1`, or `yes` to enable debug mode by default

#### Features

- List available tools with parameters
- Call tools directly via REST endpoint (`/tools/call`)
- Progress display with tqdm during tool execution
- Real-time SSE streaming of envelope updates
- Envelope status checking
- Simple JSON input/output

#### Examples

```bash
# Port-forward gateway first
kubectl port-forward -n asya-e2e svc/asya-gateway 8089:8080

# List tools
asya-mcp list

# Call echo tool
asya-mcp call echo '{"message": "test"}'

# Multi-actor pipeline
asya-mcp call process-image '{"url": "https://example.com/img.jpg", "filters": ["resize", "blur"]}'

# Stream updates in real-time
asya-mcp stream abc-123-def-456
```

### asya-mcp-forward

Quick kubectl port-forward helper for accessing asya-gateway MCP server.

Automatically finds a free local port, sets up port-forwarding to the gateway, and outputs the URL. All logs go to stderr, only the URL goes to stdout for easy environment variable capture.

#### Usage

```bash
# Basic usage - auto-detect free port and forward to asya-gateway in asya-e2e namespace
export ASYA_CLI_MCP_URL=$(asya-mcp-forward)
asya-mcp list

# Custom namespace
export ASYA_CLI_MCP_URL=$(asya-mcp-forward --namespace my-namespace)
asya-mcp call echo --message hello

# Custom deployment name
export ASYA_CLI_MCP_URL=$(asya-mcp-forward --deployment my-gateway)

# Custom ports
export ASYA_CLI_MCP_URL=$(asya-mcp-forward --port 8080 --local-port 9000)

# Skip health check (faster startup, but no verification)
export ASYA_CLI_MCP_URL=$(asya-mcp-forward --no-check-health)

# Keep port-forward running in foreground (useful for debugging)
asya-mcp-forward --keep-alive
```

#### Options

- `--namespace, -n`: Kubernetes namespace (default: `asya-e2e`)
- `--deployment, -d`: Deployment name (default: `asya-gateway`)
- `--port, -p`: Target port on the deployment (default: `8080`)
- `--local-port, -l`: Local port to use (default: auto-detect free port)
- `--check-health`: Verify gateway health endpoint after port-forward (default: `true`)
- `--no-check-health`: Skip health check for faster startup
- `--keep-alive`: Keep port-forward running until interrupted (default: `false`)

#### Features

- Auto-detects free local ports (scans 8080-9000 range)
- Reuses existing healthy port-forwards when available
- Verifies gateway health endpoint before returning URL
- All logs to stderr, only URL to stdout for `$()` capture
- Smart cleanup of stale port-forwards
- Retry logic for robust port-forward establishment

#### Complete Example

```bash
# Start port-forward and set URL in one command
export ASYA_CLI_MCP_URL=$(asya-mcp-forward)

# Now use asya-mcp with the forwarded URL
asya-mcp list
asya-mcp call echo --message "hello from kubectl port-forward"
asya-mcp call process-data --input "test data"

# Check what URL is being used
echo $ASYA_CLI_MCP_URL
# Output: http://localhost:8123 (or whatever free port was found)
```

## Comparison with Other MCP CLIs

### wong2/mcp-cli
JavaScript/TypeScript CLI inspector for MCP servers. Good for general MCP debugging.

**Install**: `npx @wong2/mcp-cli`

**Pros**: Standard MCP client, supports stdio/SSE transports
**Cons**: Requires Node.js, more complex for simple tool calls

### chrishayuk/mcp-cli
Python CLI with LLM integration for conversational tool usage.

**Install**: `uvx mcp-cli`

**Pros**: Full LLM integration, chat mode
**Cons**: Requires AI models (Ollama/OpenAI), overkill for debugging

### asya-mcp (this tool)
Minimal Python CLI specifically for asya gateway debugging.

**Pros**:
- No AI/LLM required
- Direct REST API calls
- Built-in progress display (tqdm)
- Asya🎭-specific features (envelope tracking)
- Super simple, single file

**Cons**:
- Only works with asya gateway
- Limited to HTTP transport
