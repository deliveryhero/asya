---
description: "CLI reference: asya mcp, asya flow, asya init, asya build, asya k apply commands"
---

# CLI

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

Compile a flow from a `.py` source file into Kubernetes manifests.

```bash
asya compile FLOW_NAME -f SOURCE_FILE [OPTIONS]
```

FLOW_NAME is a kebab-case identifier used across all commands.

| Option | Description |
|--------|-------------|
| `-f`, `--file` | Path to flow `.py` source file (required) |
| `-o`, `--output-dir` | Override compiled output directory |
| `-I`, `--python-path` | Add directory to Python import path for compile-time resolution (repeatable) |
| `--plot` | Generate Graphviz DOT and PNG flow diagrams |
| `--plot-format` | Diagram format: `svg` or `png` (default: png) |
| `-v`, `--verbose` | Detailed output (shows handler resolution) |
| `--strict` | Treat warnings as errors |

The compiler uses `skaffold.yaml` as the single source of truth for image names.
Skaffold artifact context directories are automatically added to `sys.path` for
bare-script handler imports.

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

### `asya patch`

Patch compiled flow manifests with kustomize overrides. Requires exactly one
scope: `--actor` or `--gateway`.

```bash
asya patch FLOW_NAME [KEY=VALUE...] --actor NAME [OPTIONS]
asya patch FLOW_NAME [KEY=VALUE...] --gateway [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-a`, `--actor` | Target a specific actor (accepts function name or manifest name) |
| `--gateway` | Target gateway flow registration |
| `--context` | Write to overlay (default: common/) |
| `-p` | Raw JSON patch (escape hatch, actors only) |
| `--remove` | Remove a key from the patch (repeatable, e.g. `--remove env.FOO`) |

**Actor patches:**

```bash
asya patch text-flow --actor analyze scaling.min=1
asya patch text-flow --actor analyze env.MY_VAR=value
asya patch text-flow --actor analyze env.API_KEY=secret:my-secret:key
asya patch text-flow --actor analyze --remove env.OLD_VAR
```

Env shorthand: `env.NAME=value` (plain), `env.NAME=secret:name:key` (secretKeyRef),
`env.NAME=configmap:name:key` (configMapKeyRef).

Scaling shorthand: `scaling.min`, `scaling.max`, `scaling.cooldown`, `scaling.polling`.

**Gateway patches:**

```bash
asya patch text-flow --gateway expose=true description="Analyze text" mcp=true a2a=true
asya patch text-flow --gateway expose=true --context dev
asya patch text-flow --gateway expose=false --context dev
```

### `asya render` (alias: `show`)

Render kustomize manifests for a compiled flow.

```bash
asya render FLOW_NAME [--context CTX] [--actor NAME]
```

| Option | Description |
|--------|-------------|
| `--context` | Overlay context to select (uses `common/` or `base/` if omitted) |
| `-a`, `--actor` | Show only this actor (accepts function name or manifest name) |

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
