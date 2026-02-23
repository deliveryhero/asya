---
title: "Gateway Dynamic Tool Exposure via CLI"
priority: 2 # medium
type: epic
---


Enable data scientists to expose compiled flows as MCP tools (and future A2A agents) via `asya expose`, with the gateway dynamically reloading tool configurations without restarts.

## Motivation

Compiled flows need a way to become discoverable MCP tools (and eventually A2A agents) in the gateway. Currently, tool configuration is static YAML loaded at startup -- any change requires a gateway restart, interrupting active SSE connections and in-flight requests.

## Design Direction

### No New CRDs

Following the same rationale as the AsyncFlow ADR (labels over CRDs for flow grouping), tool/agent registration should avoid introducing new CRDs (`AsyncTool`, `GatewayConfig`, etc.). Instead:

- **Singleton ConfigMap** (`gateway-tools`) -- holds all tool definitions, mounted into the gateway pod
- **CLI updates** -- `asya expose <flow-name>` patches the ConfigMap via `kubectl patch`
- **fsnotify hot-reload** -- gateway watches the mounted config directory, reloads on file changes

### Flow: `asya expose`

1. DS runs `asya expose order-processing`
2. CLI finds entrypoint actor by label (`asya.sh/flow-role=entrypoint`)
3. CLI reads tool metadata from annotations / flow.py (name, description, parameters)
4. CLI patches `gateway-tools` ConfigMap
5. Kubelet syncs ConfigMap to mounted volume
6. Gateway's fsnotify detects change, reloads tool config

### Gateway Hot-Reload

Three options were evaluated:

| Option | Mechanism | Verdict |
|--------|-----------|---------|
| A. CRD-based (`AsyncTool`) | Gateway watches new CRD via informers | Rejected -- adds CRD, contradicts labels-over-CRDs direction |
| B. ConfigMap watch | K8s informers on labeled ConfigMaps | Viable but couples gateway to K8s API |
| **C. File watch (fsnotify)** | Watch mounted config directory for changes | **Chosen** -- works outside K8s too, simple, ~30 LOC |

Implementation: add `fsnotify` dependency, watch `ASYA_CONFIG_PATH`, debounce (500ms), call `LoadFromDir`, re-register tools. Thread-safe registry updates required (existing requests must complete).

### Key Design Questions (needs more design)

- ConfigMap structure: one file per tool vs single aggregated YAML?
- Tool parameter detection: how does CLI infer parameters from flow.py?
- A2A agent exposure: what metadata is needed beyond MCP tool definition?
- Multi-namespace: how does the gateway discover tools across namespaces?
- Graceful tool removal: in-flight requests for removed tools should complete normally
- Backwards compatibility: static YAML configuration must remain supported

## Related Tasks

- `misc/1fiyl8` -- Add fsnotify file watcher to asya-gateway (implementation prerequisite)
- `misc/1f9jeu` -- Implement `asya flow deploy`/`undeploy`/`expose` CLI commands
