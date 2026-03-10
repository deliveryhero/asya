---
title: "CLI: asya expose command (gateway ConfigMap generation)"
priority: 2 # medium
---

## Scope

Implement the `asya expose` CLI command that generates `configmap-flows.yaml`
in the kustomize `base/` directory. This is a local-only operation — no cluster
interaction.

### What it does

1. Accept same target types as `asya compile` (`.py` file, kebab-name)
2. Auto-compile if given a `.py` file and manifests don't exist yet
3. Read compiled manifests in `base/`, find actor with
   `asya.sh/flow-role: entrypoint` label
4. Extract flow metadata: name, description (from docstring), input schema
   (from function signature)
5. Generate `base/configmap-flows.yaml` with gateway tool registration
6. Update `base/kustomization.yaml` to include the new resource

### CLI flags

| Flag | Description |
|------|-------------|
| `--description` | Flow description (falls back to docstring) |
| `--timeout` | E2E timeout in seconds |
| `--protocol mcp\|a2a` | Protocol (default: configurable) |
| `--input-schema` | JSON Schema inline |
| `--input-schema-file` | JSON Schema from file |

### Behaviors

- Idempotent: re-running overwrites `configmap-flows.yaml`
- `asya unexpose` removes `configmap-flows.yaml` from `base/`
- Per-context control: users add `$patch: delete` in overlay to exclude

## Dependencies

- [hox4] Manifest stamping (for base/ directory structure)
- [5ifn] Compile command (for auto-compile on .py input)

## References

- `.aint/aints/asya-lab/rfc.md` §8.1.2 — gateway exposure, ConfigMap schema,
  SSA field managers, CLI flags, per-context control
- `.aint/aints/asya-lab/rfc.md` §5.1 — expose as top-level command
- `a2a-protocol-compliance-gateway/adr.configmap-flow-registry.md` — ConfigMap
  flow registry design
