---
title: "Phase 2: Flatten workload structure, promote handler, rewrite flavor merge"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/xrd-v2/lfcf.phase-2-flatten-workload-structure-promote-handler-rewrite
  - branch:xrd-v2/lfcf.phase-2-flatten-workload-structure-promote-handler-rewrite
  - pr:303
dependencies:
  - af25
---





## Summary

Flatten `workload.template.spec.containers[]` into root-level spec fields. Promote `handler` to first-class field. Rewrite `function-asya-flavors` with type-aware overlap merge (~50 LOC).

## Scope

### XRD (`xrd-asyncactor.yaml`)
- Remove `workload` object (kind, replicas, template.spec)
- Add root-level fields: `image`, `handler`, `env`, `resources`, `tolerations`, `nodeSelector`, `volumes`, `volumeMounts`, `replicas`
- `handler` becomes first-class field (was buried in env vars as ASYA_HANDLER)

### Compositions (all 3: SQS, RabbitMQ, PubSub)
- Rewrite render-deployment: read `$xr.spec.image`, `$xr.spec.resources`, `$xr.spec.tolerations`, etc. instead of `$xr.spec.workload.template.spec.containers[0]`
- Inject `spec.handler` as ASYA_HANDLER env var on runtime container
- Remove `$workload.kind` reads (always Deployment)
- Read `spec.replicas` directly instead of `spec.workload.replicas`

### function-asya-flavors (`src/function-asya-flavors/`)
- Complete rewrite: ~50 LOC with type-aware overlap merge
- Lists (stateProxy, tolerations, secretRefs, volumes): append across flavors
- Maps (nodeSelector): merge keys, error on same-key conflict
- Scalars/structs (scaling, resources): error on flavor overlap
- Actor inline spec always wins silently
- Remove merge.go structs (ActorSpecSchema, WorkloadSchema, TemplateSchema)
- Remove DeepMerge, mergeByName, field allow/deny lists

### Injector (`src/asya-injector/`)
- Update `asyncactor.go`: read `spec.image` instead of `spec.workload.template.spec.containers`
- Read `spec.handler` directly

### Helm charts
- `asya-actor/`: update values.yaml (flat structure), update templates
- `asya-crew/templates/`: update sink.yaml, sump.yaml, resume.yaml, pause.yaml, checkpoint-s3.yaml
- `asya-playground/templates/`: update hello-actor.yaml, chaos-actors.yaml

### Examples (`examples/asyas/`)
- Update all ~12 example YAML files to flat spec

### Test manifests
- `testing/e2e/charts/asya-test-actors/`: update all templates
- `testing/e2e/`: update test-asyncactor-spec.yaml jsonpath queries
- Unit tests: rewrite fn_test.go, merge_test.go fixtures
- Injector unit tests: update spec fixtures

## Test strategy
- Unit tests: all function-asya-flavors and injector tests rewritten
- E2E tests: all test actors use new flat spec, all assertions updated
- `make test-unit` and `make test-e2e` must pass


## Documentation

Update all documentation to reflect the flat XRD structure.

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
