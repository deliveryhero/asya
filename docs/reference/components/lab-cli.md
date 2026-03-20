
# CLI Reference

Command reference for the `asya` developer toolkit (package: `asya-lab`).

## Installation

From local repository:
```bash
uv pip install -e ./src/asya-lab
#call with: uv run asya...
```
Or as uv tool:
```bash
uv tool install src/asya-lab
#call with: asya...
```

Or from remote repository:
```bash
uv tool install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-lab
#call with: asya...
```

## Commands

### `asya init`

Scaffold a `.asya/` project directory with default configuration and
compiler templates.

```bash
asya init [--registry REGISTRY] [--dir TARGET_DIR]
```

| Option | Description |
|--------|-------------|
| `--registry` | Container image registry (e.g. `ghcr.io/my-org`). Prompted if omitted. |
| `--dir` | Target directory (default: current directory) |

### `asya compile`

Compile a flow from a `.py` source file or recompile from existing manifests.

```bash
asya compile TARGET [OPTIONS]
```

TARGET can be:
- A `.py` file (or `file.py:function`) — compile flow from source
- A kebab-case or snake_case name — recompile from existing manifests

| Option | Description |
|--------|-------------|
| `--output-dir`, `-o` | Where to write generated router files |
| `--plot` | Generate Graphviz DOT and PNG flow diagrams |
| `--plot-format` | Diagram format (default: svg) |
| `--verbose` | Detailed output |
| `--force` | Overwrite existing files |
| `--flow-name` | Override the flow function name |

### `asya validate`

Validate a flow source file without generating code.

```bash
asya validate FLOW_FILE
```

### `asya build`

Build container images for compiled flows. Reads build entries from
`.asya/config.yaml`, resolves variables, and executes shell commands.

```bash
asya build [TARGET]
```

TARGET is an optional flow name. Without it, all build entries are executed.

### `asya expose`

Register a compiled flow as a tool in the gateway's `gateway-flows` ConfigMap.

```bash
asya expose TARGET
```

### `asya unexpose`

Remove a flow from the gateway's `gateway-flows` ConfigMap.

```bash
asya unexpose TARGET
```

### `asya show`

Render kustomize manifests for a compiled flow.

```bash
asya show TARGET [--context CTX]
```

| Option | Description |
|--------|-------------|
| `--context` | Overlay context to select (uses `common/` or `base/` if omitted) |

### `asya status`

Show status of all compiled flows (compiled, exposed, actor count).

```bash
asya status
```

### `asya config get`

Get a configuration value by dot-separated key from `.asya/config.yaml`.

```bash
asya config get KEY [--dir START_DIR] [--arg KEY=VALUE] [-o yaml|json]
```

| Option | Description |
|--------|-------------|
| `--dir` | Start directory for config discovery (default: cwd) |
| `--arg` | Set arg resolver value (repeatable) |
| `-o`, `--output` | Output format: `yaml` or `json` |

### `asya k` (aliases: `kube`, `kubernetes`)

Kubernetes cluster commands. Interact with deployed actors and flows.

```bash
asya k SUBCOMMAND [OPTIONS]
```

Subcommands include apply, delete, status, logs, edit, context, and secret
management. Requires a `.asya/` project directory with context configuration.

### `asya mcp`

CLI for interacting with the MCP Gateway.

#### List Tools

```bash
asya mcp list
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

#### Call Tool

```bash
asya mcp call text-processor --text="Hello world"
```

Output (with SSE streaming):
```
[.] Message ID: 5e6fdb2d-1d6b-4e91-baef-73e825434e7b
Processing: 100% |████████████████████████████████████| , succeeded
{
  "id": "5e6fdb2d-1d6b-4e91-baef-73e825434e7b",
  "status": "succeeded",
  "result": {
    "response": "Processed: Hello world"
  }
}
```

#### Get Status

```bash
asya mcp status 5e6fdb2d-1d6b-4e91-baef-73e825434e7b
```

#### Port-Forward

```bash
asya mcp port-forward
```

Automatically port-forwards `asya-gateway` service to `localhost:8080`
and keeps the connection alive until interrupted.

#### Configuration

Set gateway URL:
```bash
export ASYA_CLI_MCP_URL=http://localhost:8089/
```

**See**: `src/asya-lab/README.md` for advanced usage.
