# RFC: VSCode Extension and Standalone Web UI

## Status

Draft

## Summary

This RFC defines the architecture for two client surfaces -- a VSCode extension
and a standalone web UI -- that share the same React component library and
communicate with a local `asya serve` process over HTTP and WebSocket. The design
avoids LSP: `asya serve` is a general-purpose API server, not a language server.

## Motivation

Developers working with Asya actor meshes need visibility into flow topology,
actor status, logs, and configuration. Two deployment contexts exist:

1. **VSCode users** want panels embedded in their editor.
2. **Non-VSCode users** (or CI dashboards) want a browser-based UI with
   identical functionality.

Both contexts should render the same components and talk to the same backend.
The `asya serve` command (part of the CLI/SDK epic 1jpc) provides that backend.

## Architecture Overview

```
+--------------------------------------------+
|  VSCode Extension (TypeScript)             |
|                                            |
|  +-----------+    postMessage   +--------+ |
|  | Extension |<---------------->|Webview | |
|  | Host      |                  |Panel   | |
|  +-----+-----+                  |[React] | |
|        |                        +--------+ |
|        | HTTP / WS                         |
+--------|-----------------------------------+
         v
   +-------------+         +----------------+
   | asya serve  |<------->| Standalone Web |
   | (Python)    |  HTTP/WS| (React SPA)    |
   | FastAPI     |         +----------------+
   +------+------+
          |
   local filesystem, Docker, kubectl
```

**Key points:**

- The VSCode extension host spawns `asya serve` as a child process on
  activation and kills it on deactivation.
- Webview panels load React bundles that communicate with the extension host
  via `postMessage`. The extension host relays requests to `asya serve`
  over HTTP/WebSocket.
- The standalone web SPA is served directly by `asya serve` and uses the
  same React components, talking to the same HTTP/WS endpoints.
- `asya serve` always runs locally on the developer's machine. It is
  context-aware: it reads ASYA_CONTEXT (or a flag) to determine which
  cluster, namespace, or docker-compose project to operate on.

## TS-Python Bridge

### Protocol

`asya serve` exposes a local HTTP+WebSocket server built on FastAPI (or
Starlette). It is NOT an LSP server -- it handles arbitrary REST and streaming
endpoints relevant to the Asya developer workflow.

### Lifecycle

| Context        | How `asya serve` starts                         |
|----------------|-------------------------------------------------|
| VSCode         | Extension host spawns it as a subprocess        |
| Standalone web | User runs `asya serve --port=8080` manually     |

In both cases the same binary/entry point is used. The extension discovers
the port from stdout or a well-known file.

### Communication

- **REST** for request/response operations (compile, deploy, config
  read/write, status snapshots).
- **WebSocket** for streaming operations (log tailing, real-time status
  updates).
- A single protocol serves all UI surfaces. The VSCode extension host acts
  as a thin relay, forwarding webview postMessage calls to HTTP/WS and
  returning responses.

## Webview Panels

### Flow Diagram Viewer

- Renders the compiled DOT or manifest into an interactive graph.
- Nodes are clickable. Clicking a node opens a detail pane showing:
  - Actor configuration (image, handler, env vars)
  - Current replica count
  - Queue depth (messages pending)
  - Recent logs for that actor
- Layout is driven by compiled flow output; no manual positioning.

### Actor Status Dashboard

- Grid or list of all actors in the current context.
- Each actor shows: name, status (running/scaled-to-zero/error), replica
  count, queue depth, last message timestamp.
- Updates in real time via WebSocket subscription.

### Log Streamer

- Streams logs from one or more actors simultaneously.
- Each actor's log lines are prefixed with the actor name in a distinct
  color, similar to `docker compose logs`.
- Supports filtering by actor name, log level, and free-text search.
- Auto-scrolls with a "pin to bottom" toggle.

### Config Editor

- Reads and writes `actor.yaml` and `.env` files from the local
  `deploy/` directory (or whichever path the context specifies).
- Provides a YAML editor with syntax highlighting.
- Validates against the AsyncActor schema before saving.
- Writes go back to the local filesystem via `asya serve` -- no direct
  file access from the webview.

## Standalone Web

Running `asya serve --port=8080` starts the same FastAPI server. In
standalone mode it additionally serves the React SPA as static files from
a bundled directory.

Functionality is identical to the VSCode panels:

- Flow diagram viewer
- Actor status dashboard
- Log streamer
- Config editor

This mode is intended for developers who do not use VSCode, or for
displaying a shared dashboard (e.g., on a wall monitor or in CI).

## React Components (`@asya/ui`)

All UI components are written in TypeScript and published as the `@asya/ui`
package. They are consumed by both the VSCode webview and the standalone SPA.

### FlowDiagram

Interactive directed graph rendered from a compiled manifest or DOT
definition. Supports zoom, pan, and click-to-select. Selected node emits an
event consumed by the parent to show detail panels.

### ActorCard

Displays status, configuration summary, and key metrics for a single actor.
Used inside the flow diagram detail pane and the status dashboard.

### LogViewer

Streaming log display with actor-name prefix coloring. Accepts a WebSocket
URL and renders incoming lines incrementally. Supports search and level
filtering.

### StatusDashboard

Overview grid of all actors in a context. Each cell is an ActorCard.
Subscribes to WebSocket status updates for live refresh.

### ConfigEditor

Monaco-based YAML editor for actor configuration files. Loads content via
REST, validates on save, and writes back via REST. Displays validation
errors inline.

## `asya serve` API

### REST Endpoints

| Method | Path                          | Description                      |
|--------|-------------------------------|----------------------------------|
| POST   | /api/compile                  | Compile a flow DSL file          |
| POST   | /api/deploy                   | Deploy actors from manifest      |
| DELETE | /api/deploy/{name}            | Undeploy an actor                |
| GET    | /api/actors                   | List actors in current context   |
| GET    | /api/actors/{name}            | Actor detail (config, status)    |
| GET    | /api/actors/{name}/config     | Read actor config file           |
| PUT    | /api/actors/{name}/config     | Write actor config file          |
| GET    | /api/flow                     | Get compiled flow manifest       |
| GET    | /api/health                   | Server health check              |

### WebSocket Endpoints

| Path                          | Description                      |
|-------------------------------|----------------------------------|
| /ws/logs                      | Stream logs (query: actor, level)|
| /ws/status                    | Real-time actor status updates   |

### Context Awareness

`asya serve` reads ASYA_CONTEXT (environment variable or CLI flag) to
determine the operational target:

- **docker-compose**: reads compose files, runs docker commands locally
- **kubernetes**: uses kubeconfig to query the target cluster/namespace
- **local**: operates on local files only (compile, config edit)

The context determines which backends are available. For example, log
streaming requires a running docker-compose or Kubernetes context; compile
and config editing work in any context.

## Future Considerations

### Pyodide for In-Browser Compilation

The Flow DSL compiler is pure Python with no native dependencies. A future
iteration could bundle it via Pyodide so the standalone web UI can compile
flows entirely in the browser, removing the requirement for a local Python
installation for read-only / compile-only use cases.

### LSP Integration for Flow DSL

A dedicated LSP server could provide language features for `.py` flow files:

- Syntax error highlighting specific to Flow DSL constraints
- Autocompletion for actor names referenced in the flow
- Inline diagnostics (e.g., "loops not supported", "parameter must be
  named p")

This would complement (not replace) `asya serve`, which handles runtime
operations.

### Real-Time Collaboration

WebSocket infrastructure could be extended to support multi-user scenarios:

- Shared dashboard viewing with cursor presence
- Collaborative config editing with conflict resolution
- Useful for pair programming or team debugging sessions

## Related Epics

- **1jow** -- Client UX Design (parent epic; defines overall UX patterns)
- **1jpc** -- CLI and SDK (`asya serve` is implemented as part of the SDK)

## Decision Log

| Decision                                      | Rationale                                                  |
|-----------------------------------------------|------------------------------------------------------------|
| FastAPI over LSP                              | `asya serve` is a general-purpose API, not a language tool |
| Shared React components (`@asya/ui`)          | Single source of truth for both VSCode and standalone web  |
| Extension host as relay, not direct WS        | Webviews cannot open WebSocket connections directly        |
| `asya serve` always local                     | Avoids auth/security complexity of remote API servers      |
| Context-aware via ASYA_CONTEXT                | Consistent with CLI conventions from epic 1jpc             |
