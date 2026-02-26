---
title: Client VSCode Extension and Standalone Web UI
priority: 3 # low
type: epic
dependencies: [1jow, 1jpc]
---

Visual developer experience for Asya via VSCode extension and standalone web UI. Both surfaces share the same React components and connect to the Python SDK via `asya serve` (local HTTP/WebSocket server).

## Scope

- VSCode extension that spawns `asya serve` on activation
- React webview panels: flow diagram viewer (clickable nodes), actor status dashboard, log streamer, config editor
- Standalone web SPA served by `asya serve` with identical functionality
- Shared React component library (`@asya/ui`): FlowDiagram, ActorCard, LogViewer, StatusDashboard, ConfigEditor
- `asya serve` REST/WebSocket API for all UI operations

## Architecture

- Extension host (TypeScript) manages `asya serve` lifecycle and relays postMessage between webviews and Python server
- React webviews are sandboxed -- no direct Python access
- `asya serve` is context-aware: shows data from current ASYA_CONTEXT (k8s-stg, docker, etc.)
- Same server, same API, same components for both VSCode and standalone web

## Key UX Requirements

- Flow diagram: compiled graph rendered with clickable actor nodes
- Clicking a node: shows actor config, logs, replica count, queue depth
- Config editing: read/write actor.yaml and .env files through the UI (writes to local deploy/ files)
- Log streaming: colorful actor-name prefix (like docker compose logs)
- Real-time status updates via WebSocket

## Related Epics

- 1jow: Client UX Design (parent design document)
- 1jpc: CLI and SDK (provides `asya serve` and SDK functions)
