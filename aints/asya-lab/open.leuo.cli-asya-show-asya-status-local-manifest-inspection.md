---
title: "CLI: asya show and asya status (local manifest inspection)"
priority: 2 # medium
---

## Scope

Implement two local-only CLI commands for inspecting compiled state:

### asya show <target> [--context ctx]

Renders effective manifests via `kustomize build`:
```bash
asya show order-processing --context stg
# kustomize build .asya/manifests/order-processing/overlays/stg/
```

- Uses `kubectl apply -k` (kustomize bundled with kubectl, no extra binary)
- Accepts same target types as compile
- `--context` selects overlay (defaults to `default_context` from config)
- Output to stdout (pipeable to `kubectl apply -f -` or `less`)

### asya status

Local source of truth — outer-join table across two data sources:

| Column | Source |
|--------|--------|
| SOURCE | `.py` files with `@flow`/`@actor` decorators |
| COMPILED | `.asya/manifests/<flow>/` YAML files |

Scans `var.project_root` for decorated functions, matches against compiled
manifests. No cluster access needed.

## Dependencies

- [pyt1] Config system (for context resolution)
- [hox4] Manifest stamping (for manifest directory structure)

## References

- `.aint/aints/asya-lab/rfc.md` §5.1 — top-level commands
- `.aint/aints/asya-lab/rfc.md` §5.7 — list and discovery, data sources
