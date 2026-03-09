---
title: "Phase 3: Update documentation for flat XRD"
priority: 2 # medium
dependencies:
  - lfcf
---

## Summary

Update all documentation to reflect the flat XRD structure after Phase 2.

## Scope

### Architecture docs
- `docs/architecture/asya-actor.md`: update example with flat spec (lines 66-75)
- `docs/architecture/asya-crossplane.md`: update workload template references (line 76)
- `docs/architecture/asya-flow.md`: update any AsyncActor examples

### Quickstart docs
- `docs/quickstart/for-platform-engineers.md`: update crew actor examples (lines 96-99)
- `docs/quickstart/for-ds-engineers.md`: update actor examples if present

### AGENTS.md
- Update handler signature section (still valid but may reference old env var pattern)
- Update envelope protocol section if it references workload
- Update any AsyncActor YAML examples

### Tutorials and references
- Any tutorial docs showing AsyncActor YAML
- `docs/reference/` files if they reference workload structure
- README.md if it shows example actors

### RFC finalization
- Update `.aint/aints/xrd-v2/rfc.md` status from draft to accepted
- Add migration notes for users coming from v1alpha1

## Test strategy
- `make lint` passes (markdown formatting)
- No code changes — docs only
