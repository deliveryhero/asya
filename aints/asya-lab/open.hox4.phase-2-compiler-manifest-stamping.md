---
title: "Phase 2: Compiler manifest stamping (kustomize output)"
priority: 2 # medium
dependencies:
  - pyt1
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
- **Idempotent**: re-running compile with same input produces identical output

## Compiler construct prerequisites

These aints in `support-more-compiler-constructs/` should be merged first
(pushed PRs #278, #280, #281):

- [pyn3] Inline comment overrides (`# asya: <action>`)
- [n67c] Strip handler decorators by actors
- [srn2] Decorator detection and rule-based resolution
- [xx8t] Call-site decorator application (`actor(handler)(p)`)
- [2t1q] Context managers (`with`/`async with`)

Open aints to address during or after this phase:

- [w1br] `@flow` and `@unfold` markers
- [20c9] Don't generate empty start/end routers
- [ia37] Per-scope semantics for context managers

## Dependencies

- [pyt1] Phase 1: Config system

## References

- `.aint/aints/asya-lab/rfc.md` §8.1 — three-layer kustomize structure
- `.aint/aints/asya-lab/rfc.md` §8 lines 842-858 — compile steps
- `.aint/aints/asya-lab/adr.kustomize-not-extra-dependency.md` — kustomize design
- `.aint/aints/asya-lab/research-compiler-resolution.md` §3 — template stamping
