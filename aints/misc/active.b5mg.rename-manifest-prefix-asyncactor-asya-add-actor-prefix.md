---
title: "Rename manifest prefix asyncactor to asya, add actor- prefix to handler names"
priority: 3 # low
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/misc/b5mg.rename-manifest-prefix-asyncactor-asya-add-actor-prefix
  - branch:misc/b5mg.rename-manifest-prefix-asyncactor-asya-add-actor-prefix
---


## Context

Current naming convention for compiled flow manifests:
- Manifest filenames: `asyncactor-<name>.yaml`
- Actor names derived from handler: `handler_name.replace("_", "-")` (e.g. `analyze-text`)

Proposed changes:
1. Manifest filename prefix: `asyncactor-` to `asya-`
2. Handler-derived actor names get `actor-` prefix: `analyze_text` to `actor-analyze-text`
3. Router names already start with `router-`, so they become `asya-router-*`

## Scope

Affects ~28 files with `asyncactor-` references and ~161 lines with name derivation logic:
- `src/asya-lab/asya_lab/compiler/templater.py` -- `_stamp_actor`, `_to_k8s_name`
- `src/asya-lab/asya_lab/flow/codegen.py` -- handler name collection
- `.asya/templates/actor.yaml`, `router.yaml` -- manifest templates
- `deploy/helm-charts/asya-crossplane/` -- XRD, compositions
- `src/asya-sidecar/` -- queue name resolution
- All test files referencing `asyncactor-` or actor names
- All compiled example outputs

## Migration concern

Existing deployed actors use `asyncactor-` prefixed manifests. Need to
decide: breaking change (major version) or dual-naming support during transition.

## Acceptance criteria

- [ ] Manifest filenames use `asya-` prefix
- [ ] Handler-derived actor names prefixed with `actor-`
- [ ] Router names: `asya-router-*` (already start with router-)
- [ ] All tests updated
- [ ] Compiled examples regenerated
- [ ] Migration path documented
