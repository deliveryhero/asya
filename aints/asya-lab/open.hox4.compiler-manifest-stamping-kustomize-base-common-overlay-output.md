---
title: "Compiler: manifest stamping (kustomize base/common/overlay output)"
priority: 2 # medium
---

## Scope

Extend the flow compiler to output kustomize-structured manifests instead of
just `routers.py`. After compilation, `.asya/manifests/<flow>/` should contain:

1. **base/**: AsyncActor XR manifests for each actor + routers, ConfigMap for
   router code, `kustomization.yaml` listing all resources. Fully regenerated
   on every compile.
2. **common/**: Layer for user customizations (`asya k edit`). Created once with
   empty `kustomization.yaml` referencing `../base`. Never overwritten by compiler.
3. **overlays/<context>/**: Per-context overlays. Created once per context from
   `config.yaml`. Never overwritten by compiler.

## Key behaviors

- **Recompile safety**: `base/` is fully regenerated. `common/` and `overlays/`
  are preserved across recompiles.
- **Actor template**: stamp `compiler.templates.actor` with `${dynamic:*}` values
  resolved per actor (name, handler, image, env vars)
- **Kustomization templates**: generate `kustomization.yaml` per layer with
  correct resource/patch references
- **`--flow`/`--actor` naming**: support naming flags for flow and actor names
  (single name when unambiguous, `func=name` mapping for multiple)
- **Idempotent**: re-running compile with same input produces identical output

## Dependencies

- [pyt1] Config system (for loading templates, build entries, var interpolation)

## References

- `.aint/aints/asya-lab/rfc.md` §8.1 — three-layer kustomize structure
- `.aint/aints/asya-lab/rfc.md` §8 lines 842-858 — compile steps
- `.aint/aints/asya-lab/adr.kustomize-not-extra-dependency.md` — kustomize design
- `.aint/aints/asya-lab/research-compiler-resolution.md` §3 — template stamping
