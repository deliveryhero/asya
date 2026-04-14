---
title: Adapt e2e flow tests to use asya-lab CLI for compilation instead of hand-crafted Helm charts
status: open
priority: 2
---

## Problem

The e2e flow tests deploy compiled flow routers via bespoke Helm chart templates
(`nested-if-routers.yaml`, `research-flow-routers.yaml`) with hand-coded handler paths
and `ASYA_HANDLER_*` env vars in `_helpers.tpl`.

Every time a flow source file changes (e.g. adding `@flow` decorator shifts all source
line numbers by +N), ALL of the following must be updated manually:
- `compiled/routers.py` — router function names encode source line numbers
- `compiled/flow.dot` + `compiled/flow.svg` — diagrams use function names as node labels
- `*-routers.yaml` — handler paths reference router function names
- `_helpers.tpl` — ASYA_HANDLER_* env vars reference router function names

This coupling was the root cause of PR #322 (three bugs from a single-decorator commit).

## Desired Solution

Use `asya flow compile` (asya-lab CLI) during the e2e deploy phase:
1. Compile flow source files → generates `routers.py`, `flow.dot`, `flow.svg`
2. Stamp Kubernetes manifests (via `--manifests-dir`) → AsyncActor YAMLs with
   correct handler paths and env vars, generated from `.asya/config.yaml`

The flow source files and `.asya/config.yaml` become the single source of truth.
The Helm chart router templates become auto-generated and no longer need manual maintenance.

## Scope

- `testing/e2e/charts/asya-test-flows/` — replace bespoke router templates with compilation-driven approach
- `testing/e2e/scripts/deploy.sh` — add `asya flow compile` step for each test flow
- Keep handler actor templates (nested-if-handlers, research-flow-handlers) — those are static
- Verify `compile-flows` pre-commit hook still works correctly

## Reference

- PR #322: the manual-sync failure this aint addresses
- `asya flow compile --help` for CLI options
- `examples/demo-kubecon/.asya/` for config.yaml + templates structure
