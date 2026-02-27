# RFC: Asya UI -- TypeScript Workspace

**Status**: Proposed
**Date**: 2026-02-27
**Epic**: 1juv.asya-ui
**Depends on**: 1jow (client UX design), 1jux (asya-lab SDK)

---

## 1. Summary

This RFC defines the architecture for `src/asya-ui/`, a pnpm monorepo workspace
containing all client-side TypeScript code. Two packages live in the workspace:

1. `packages/components/` -- `@asya/ui`, a framework-agnostic React component
   library consumed by both the VSCode extension and the standalone web SPA.
2. `packages/vscode/` -- the VSCode extension that spawns `asya serve` and
   provides editor-integrated panels for flow visualization, actor status, logs,
   and configuration.

The design avoids LSP: `asya serve` (from `asya-lab[ui]`) is a general-purpose
API server, not a language server.

---

## 2. Motivation

Developers working with Asya actor meshes need visibility into flow topology,
actor status, logs, and configuration. Three deployment contexts exist:

1. **Local VSCode users** want panels embedded in their editor (extension from
   VS Code Marketplace).
2. **Self-hosted VSCode users** access code-server via browser with the extension
   pre-installed (asya-lens Docker image).
3. **Non-VSCode users** (or ops dashboards) want a browser-based UI with
   identical functionality (standalone web via `asya serve`).

All three contexts render the same React components and talk to the same
`asya serve` backend.

---

## 3. Source Structure

```
src/asya-ui/                          # pnpm workspace root
├── package.json                      # workspace config
├── pnpm-workspace.yaml               # packages: ["packages/*"]
├── tsconfig.base.json                # shared TypeScript config
├── .eslintrc.js                      # shared linting
├── vitest.config.ts                  # shared test config
│
├── packages/
│   ├── components/                   # @asya/ui
│   │   ├── package.json              # name: "@asya/ui"
│   │   ├── tsconfig.json             # extends ../../tsconfig.base.json
│   │   ├── src/
│   │   │   ├── FlowDiagram.tsx       # Interactive directed graph
│   │   │   ├── ActorCard.tsx         # Actor status/config summary
│   │   │   ├── LogViewer.tsx         # Streaming log display
│   │   │   ├── StatusDashboard.tsx   # Overview grid of all actors
│   │   │   ├── ConfigEditor.tsx      # Monaco-based YAML editor
│   │   │   └── index.ts             # Public API
│   │   └── tests/
│   │
│   └── vscode/                       # VSCode extension
│       ├── package.json              # name: "asya-vscode"
│       ├── tsconfig.json
│       ├── src/
│       │   ├── extension.ts          # activate/deactivate, spawn asya serve
│       │   ├── server.ts             # asya serve lifecycle management
│       │   ├── relay.ts              # postMessage <-> HTTP/WS relay
│       │   ├── commands.ts           # registerCommand handlers
│       │   └── panels/               # WebviewPanel providers
│       │       ├── FlowPanel.ts
│       │       ├── StatusPanel.ts
│       │       └── LogPanel.ts
│       └── tests/
```

---

## 4. Architecture

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

### 4.1 TS-Python Bridge

`asya serve` (provided by `asya-lab[ui]`) exposes a local HTTP+WebSocket server.

| Context        | How `asya serve` starts                         |
|----------------|-------------------------------------------------|
| Local VSCode   | Extension host spawns it as a subprocess        |
| asya-lens      | Extension host spawns it inside the container   |
| Standalone web | User runs `asya serve --port=8080` manually     |

In all cases the same Python entry point is used. The extension discovers the
port from stdout or a well-known file.

### 4.2 Communication

- **REST** for request/response: compile, deploy, config read/write, status
- **WebSocket** for streaming: log tailing, real-time status updates
- Extension host acts as a thin relay, forwarding webview postMessage calls
  to HTTP/WS and returning responses

---

## 5. React Components (`@asya/ui`)

All UI components are written in TypeScript, published as `@asya/ui`, and
consumed by both the VSCode webview and the standalone SPA.

### FlowDiagram

Interactive directed graph rendered from a compiled manifest or DOT definition.
Supports zoom, pan, and click-to-select. Selected node emits an event consumed
by the parent to show detail panels.

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

---

## 6. VSCode Extension

### 6.1 Lifecycle

1. On activation: spawn `asya serve` as a child process, wait for port
2. Register commands: `asya.flow.compile`, `asya.flow.status`, `asya.actor.logs`
3. Register webview panel providers for flow diagram, status, logs
4. On deactivation: kill `asya serve` process

### 6.2 Webview Panels

Webview panels load bundled `@asya/ui` React components. Communication between
the panel and extension host uses `postMessage`:

```
Webview (React) --postMessage--> Extension Host --HTTP/WS--> asya serve
Webview (React) <--postMessage-- Extension Host <--HTTP/WS-- asya serve
```

Webviews are sandboxed and cannot directly access the filesystem, network,
or VSCode APIs. The extension host mediates all interactions.

### 6.3 Flow Diagram Viewer

- Renders compiled DOT or manifest into an interactive graph
- Clickable nodes open a detail pane showing:
  - Actor configuration (image, handler, env vars)
  - Current replica count
  - Queue depth (messages pending)
  - Recent logs for that actor
- Layout driven by compiled flow output; no manual positioning

### 6.4 Log Streamer

- Streams logs from one or more actors simultaneously
- Actor-name prefix with distinct colors (like `docker compose logs`)
- Filtering by actor name, log level, and free-text search
- Auto-scrolls with a "pin to bottom" toggle

### 6.5 Config Editor

- Reads/writes `actor.yaml` and `.env` files from local `deploy/` directory
- YAML syntax highlighting via Monaco
- Validates against AsyncActor schema before saving
- Writes go through `asya serve` REST API

---

## 7. Build Pipeline

### 7.1 @asya/ui Build

```
pnpm --filter @asya/ui build
  -> TypeScript compile + Vite bundle
  -> dist/  (JS + CSS)
```

The built assets are consumed in two ways:
1. **Standalone web SPA**: copied into `asya-lab` Python package at
   `asya/server/static/` before `uv build`
2. **VSCode webview**: bundled into the extension's `media/` directory by
   the extension build step

### 7.2 Extension Build

```
pnpm --filter asya-vscode build
  -> copies @asya/ui dist into media/
  -> esbuild bundles extension host code
  -> vsce package -> asya-vscode.vsix
```

### 7.3 CI Pipeline

```
pnpm install              # install all workspace dependencies
pnpm -r build             # build all packages (components first, then vscode)
pnpm -r test              # run all tests
pnpm -r lint              # lint all packages
```

---

## 8. Distribution

| Output | Channel | Consumer |
|---|---|---|
| `@asya/ui` JS bundle | Bundled into `asya-lab[ui]` and extension | Standalone web, VSCode webviews |
| `asya-vscode.vsix` | VS Code Marketplace | Local VSCode users |
| `asya-vscode.vsix` | Bundled into `asya-lens` Docker image | Self-hosted code-server |

`@asya/ui` is NOT published to npm separately. It is an internal workspace
package consumed at build time by the extension and by the `asya-lab` Python
package build step.

---

## 9. `asya serve` API

Defined in `asya-lab[ui]` (epic 1jux), consumed by both the extension and
standalone web. Included here for reference:

### REST Endpoints

| Method | Path                      | Description                  |
|--------|---------------------------|------------------------------|
| POST   | /api/compile              | Compile a flow DSL file      |
| POST   | /api/deploy               | Deploy actors from manifest  |
| DELETE | /api/deploy/{name}        | Undeploy an actor            |
| GET    | /api/actors               | List actors in context       |
| GET    | /api/actors/{name}        | Actor detail (config/status) |
| GET    | /api/actors/{name}/config | Read actor config file       |
| PUT    | /api/actors/{name}/config | Write actor config file      |
| GET    | /api/flow                 | Get compiled flow manifest   |
| GET    | /api/health               | Server health check          |

### WebSocket Endpoints

| Path       | Description                       |
|------------|-----------------------------------|
| /ws/logs   | Stream logs (query: actor, level) |
| /ws/status | Real-time actor status updates    |

---

## 10. Future Considerations

### Pyodide for In-Browser Compilation

The Flow DSL compiler is pure Python with no native dependencies. A future
iteration could bundle it via Pyodide so the standalone web UI can compile
flows entirely in the browser, removing the Python requirement for
compile-only use cases.

### LSP Integration for Flow DSL

A dedicated LSP server could provide language features for `.py` flow files:
syntax error highlighting, actor name autocompletion, inline diagnostics
(e.g., "loops not supported", "parameter must be named p"). This would
complement `asya serve`.

### Jupyter Widget Integration

Jupyter notebooks could render `@asya/ui` components inline via ipywidgets
or the JupyterLab extension framework. The same React components would be
reused, making three surfaces total (VSCode, standalone web, Jupyter).

---

## 11. Decision Log

| Decision | Rationale |
|---|---|
| pnpm workspace (not separate repos) | Tight coupling between components and extension; shared tooling |
| FastAPI over LSP | `asya serve` is a general-purpose API, not a language tool |
| Shared React components (`@asya/ui`) | Single source of truth for all UI surfaces |
| Extension host as relay, not direct WS | Webviews cannot open WebSocket connections directly |
| `@asya/ui` not published to npm | Internal package; only consumed at build time |
| `asya serve` always local | Avoids auth/security complexity of remote API servers |
| Context-aware via ASYA_CONTEXT | Consistent with CLI conventions from epic 1jpc/1jux |

---

## 12. Related Epics

| Epic | Relationship |
|---|---|
| 1jow (Client UX Design) | Parent design -- overall UX patterns |
| 1jux (Asya Lab) | Provides `asya serve` backend and SDK functions |
| 1juy (Asya Lens) | Docker image that bundles this extension + SDK |
| 1jpc (Client CLI) | Predecessor; detailed CLI/SDK API design |
