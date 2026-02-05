# Gateway Configuration

Define MCP tools via YAML.

## Quick Start

```bash
export ASYA_CONFIG_PATH=config/routes.yaml
./bin/gateway
```

## Minimal Example

```yaml
tools:
  - name: echo
    description: Echo message
    parameters:
      message: {type: string, required: true}
    route: [echo-actor]
```

## Complete Definition

```yaml
defaults:
  progress: false
  timeout: 300

routes:
  ml-pipeline: [prep, infer, post]

tools:
  - name: my_tool
    description: Process data
    parameters:
      input: {type: string, required: true}
      count: {type: number, default: 5}
    route: ml-pipeline  # or [step1, step2]
    progress: true
    timeout: 600
```

## Parameter Types

- `string`, `number`, `integer`, `boolean`, `array`, `object`
- Add `required: true`, `default: value`, `options: [a, b]`

## Multi-File Loading

```bash
export ASYA_CONFIG_PATH=/etc/asya/tools/  # Loads all .yaml/.yml
```

## Kubernetes Deployment

```yaml
kind: ConfigMap
metadata:
  name: gateway-config
data:
  routes.yaml: |
    tools:
      - name: my_tool
        parameters:
          input: {type: string, required: true}
        route: [my-actor]
---
# Deployment:
env:
  - name: ASYA_CONFIG_PATH
    value: /etc/asya/routes.yaml
volumeMounts:
  - {name: config, mountPath: /etc/asya}
volumes:
  - name: config
    configMap:
      name: gateway-config
```

## Examples

- `examples/routes-minimal.yaml`
- `examples/routes.yaml`
