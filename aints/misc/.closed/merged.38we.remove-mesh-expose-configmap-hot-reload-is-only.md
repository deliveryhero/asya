---
title: Remove /mesh/expose — ConfigMap+hot-reload is the only tool registration mechanism
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/misc/38we.remove-mesh-expose-configmap-hot-reload-is-only
  - branch:misc/38we.remove-mesh-expose-configmap-hot-reload-is-only
  - pr:335
---





## Context

The gateway has documentation and stale code references to a `POST /mesh/expose` endpoint that was
meant to let actors register themselves as tools/skills at runtime. This endpoint **does not exist**
as an HTTP handler — it was never implemented. However, its ghost lives in:

- `src/asya-gateway/internal/mcp/server.go:47,50` — log messages suggesting callers use `/mesh/expose`
- `src/asya-gateway/cmd/gateway/main.go:112` — comment: "API key for endpoint auth (shared by A2A and /mesh/expose)"
- `src/asya-gateway/README.md:41-56` — documents `POST /mesh/expose` and `GET /mesh/expose` as live endpoints
- `deploy/helm-charts/asya-gateway/values.yaml:134` — comment "flows are added post-deploy via /mesh/expose"

## Current State (already working)

ConfigMap-based hot-reload is already fully implemented:

- `toolstore.Watch()` (`internal/toolstore/watcher.go`) — polls `ASYA_CONFIG_PATH` dir every
  `ASYA_CONFIG_POLL_INTERVAL` (default 10s); detects changes via FNV-64a fingerprint of filenames +
  mod times + sizes; reloads atomically via `atomic.Value` swap
- `toolstore.Registry.LoadFromDir()` — reads `*.yaml`/`*.yml` files, parses `FlowsFile`, converts
  flows to `Tool` structs
- `main.go:87-103` — if `ASYA_CONFIG_PATH` is set, uses ConfigMap mode with background watcher;
  otherwise falls back to `NewInMemoryRegistry()`

The `Upsert()` method and `NewInMemoryRegistry()` are used **only in tests** — no HTTP handler
calls them in production paths.

## What Needs To Change

### Must do (cleanup of ghost references)

1. **`server.go:47,50`** — remove/reword log messages that say "use /mesh/expose API for dynamic
   registration"; replace with accurate message about ASYA_CONFIG_PATH ConfigMap
2. **`main.go:112`** — remove "/mesh/expose" from the API key comment
3. **`README.md`** — remove the `/mesh/expose` rows from the endpoint table (lines 41-42) and the
   entire "Tool Registration" section (lines 49-56) that describes it as a live API; replace with
   accurate description of ConfigMap-based registration
4. **`values.yaml:134`** — update comment from "added post-deploy via /mesh/expose" to describe
   ConfigMap patching (`kubectl patch configmap` or `asya flow expose`)

### Optional (nice-to-have)

5. **`POST /mesh/config-reload`** — add a lightweight endpoint on the mesh gateway that calls
   `registry.LoadFromDir(configPath)` immediately, bypassing the 10s poll window. Useful for
   operators or CI pipelines that need instant propagation after patching the ConfigMap. Must only
   be registered when `ASYA_CONFIG_PATH` is set. No auth needed (it's mesh-internal, not public).

### Do NOT change

- `toolstore.Upsert()` — keep for tests; it populates the in-memory registry without YAML files
- `toolstore.NewInMemoryRegistry()` — keep for tests
- The in-memory fallback in `main.go` when `ASYA_CONFIG_PATH` is unset — useful for local dev /
  zero-config testing

## Security Rationale

Actors run with minimal RBAC. They can write to their own queues but must not have network-level
write access to the gateway's tool registry. ConfigMap patching requires explicit K8s RBAC
(`patch configmaps` on the `gateway-flows` ConfigMap) — a separate, auditable permission boundary.
Dynamic HTTP registration (`POST /mesh/expose`) would bypass that boundary entirely.

## Acceptance Criteria

- No file in the codebase references `/mesh/expose` except this aint and git history
- README accurately describes ConfigMap-based tool registration
- Optionally: `POST /mesh/config-reload` endpoint exists and triggers immediate reload
- Unit tests pass (`make test-unit`)
