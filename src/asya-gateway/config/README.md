# Asya Gateway Configuration

Define MCP tools declaratively via YAML files.

## Quick Start

```bash
# Copy example
cp config/examples/routes-minimal.yaml config/routes.yaml

# Edit config to define your tools
# Run gateway
export ASYA_CONFIG_PATH=config/routes.yaml
./bin/gateway
```

## Configuration Format

### Minimal Example

```yaml
tools:
  - name: echo
    description: Echo back the input message
    parameters:
      message:
        type: string
        required: true
    route: [echo-actor]
```

### Complete Tool Definition

```yaml
# Global defaults (optional)
defaults:
  progress: false
  timeout: 300

# Named route templates (optional)
routes:
  ml-pipeline: [preprocessor, inference, postprocessor]

# Tools
tools:
  - name: my_tool
    description: Tool description shown to users

    # Parameters
    parameters:
      param_name:
        type: string          # string, number, integer, boolean, array, object
        description: Param description
        required: true        # default: false
        default: value        # optional default value
        options: [a, b, c]    # enum values (optional)

    # Route configuration
    route: [step1, step2]     # Explicit steps
    # OR
    route: ml-pipeline        # Template reference

    # Optional settings
    progress: true            # Enable SSE progress streaming
    timeout: 600              # Timeout in seconds
    metadata:                 # Custom metadata (key-value pairs)
      team: ml-team
      priority: high
```

## Parameter Types

| Type | Example | Notes |
|------|---------|-------|
| `string` | `type: string, required: true` | |
| `string` (enum) | `type: string, options: [a, b, c], default: a` | |
| `number` | `type: number, default: 10` | |
| `integer` | `type: integer, default: 10` | |
| `boolean` | `type: boolean, default: false` | |
| `array` | `type: array, items: {type: string}` | |
| `object` | `type: object` | Limited validation |

## Route Configuration

**Explicit**: `route: [parser, analyzer, summarizer]`

**Template**:
```yaml
routes:
  standard: [ingress, processor, egress]
tools:
  - name: my_tool
    route: standard
```

## Global Defaults

```yaml
defaults:
  progress: true
  timeout: 300

tools:
  - name: tool1        # Inherits defaults
  - name: tool2
    progress: false   # Override
```

## Multi-File Loading

```bash
export ASYA_CONFIG_PATH=/etc/asya/tools/  # Loads all .yaml/.yml files
```

Files are merged (duplicates cause error, last defaults win).

## Environment

- `ASYA_CONFIG_PATH` - Config file or directory (optional, falls back to hardcoded tools)

## Validation

Startup validation prevents errors:
- Unique tool names
- Valid routes and templates
- Valid parameter types

## Examples

- `examples/routes-minimal.yaml` - Starter config
- `examples/routes.yaml` - All features

## Kubernetes Deployment

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: asya-gateway-config
data:
  routes.yaml: |
    tools:
      - name: my_tool
        parameters:
          input: {type: string, required: true}
        route: [my-actor]
---
# In Deployment spec:
env:
  - name: ASYA_CONFIG_PATH
    value: /etc/asya/routes.yaml
volumeMounts:
  - name: config
    mountPath: /etc/asya
volumes:
  - name: config
    configMap:
      name: asya-gateway-config
```

## Migration

Backward compatible - gateway uses hardcoded tools if `ASYA_CONFIG_PATH` not set.

To migrate: Extract tools to YAML → Set `ASYA_CONFIG_PATH` → (Optional) Remove hardcoded code
