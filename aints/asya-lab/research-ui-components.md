# Research: @asya/ui React Component Library

**Date**: 2026-03-10
**Status**: Informational
**Context**: Design of the shared React component library consumed by Jupyter
(anywidget), VSCode extension (webview panels), and `asya serve` (standalone
web). Impacts Phase 3 (Jupyter magics) and Phase 4 (`asya serve`).

**Related docs**:
- `rfc.md` §15.3–15.4 — Jupyter visualization and `@asya/ui` reuse
- `research-compiler-resolution.md` — compiler output (DOT, manifests)
- Epic 1juv (Asya UI) — `@asya/ui` scope
- Epic 1juy (Asya Lens) — Docker image packaging

---

## 1. Package Identity

**Name**: `@asya/ui`
**Published to**: npm (or GitHub Packages)
**Versioned**: independently from `asya-lab` Python package
**Consumers**: three host applications, one shared library

```
@asya/ui                    ← React component library (this doc)
├── asya-lab[jupyter]       ← anywidget wrapper (Python + JS bridge)
├── asya-vscode             ← VSCode extension (webview panels)
└── asya-lab[ui]            ← standalone web app (asya serve)
```

Each consumer bundles `@asya/ui` at build time. No runtime CDN loading.

---

## 2. Component Inventory

### 2.1 Phase 3 Components (Jupyter + VSCode)

| Component | Purpose | Data source |
|---|---|---|
| `FlowDiagram` | Interactive directed graph (actors, routers, edges) | Compiler graph JSON |
| `ActorNode` | Custom React Flow node — name, role badge, state border | Part of FlowDiagram |
| `ActorDetail` | Side panel — config summary, replicas, queue depth | Provider context |
| `LogViewer` | Streaming log lines with actor-name coloring | Provider context (SSE) |
| `TaskProgress` | Progress bar — %, current actor, status | Provider context (SSE) |
| `StatusBadge` | Inline status indicator (running, failed, etc.) | Props only |

### 2.2 Phase 4 Components (asya serve)

| Component | Purpose | Data source |
|---|---|---|
| `StatusDashboard` | Grid of actor cards with live updates | Provider context (WS) |
| `ActorCard` | Summary card — status, replicas, queue depth | Provider context |
| `ToolBrowser` | MCP tool list, call UI, result display | HTTP |
| `ConfigEditor` | YAML editor with schema validation (Monaco/CodeMirror) | HTTP |

### 2.3 Shared Primitives

| Component | Purpose |
|---|---|
| `AsyaProvider` | React context provider (interface only — each host implements) |
| `useAsya()` | Hook to access actor data, status, log streams |
| `StatusColor` | Color mapping for task/actor status values |
| `theme` | Design tokens (colors, spacing, typography) |

---

## 3. FlowDiagram — React Flow

### 3.1 Library Choice

**React Flow** (reactflow.dev). Reasons:
- Built-in zoom, pan, minimap, controls
- Custom node components (ActorNode renders inside React Flow)
- Custom edge labels (condition labels on conditional branches)
- Active maintenance, MIT license, large ecosystem
- Fits React component model natively

### 3.2 Graph Data Format

The compiler emits a graph JSON alongside DOT. The JSON is the source of
truth for the interactive view; the DOT is for static PNG/SVG output.

```json
{
  "flow": "order-processing",
  "nodes": [
    {
      "id": "start-order-processing",
      "type": "router",
      "role": "entrypoint",
      "label": "start",
      "handler": "compiled_routers.start_order_processing",
      "mutations": ["p['status'] = 'processing'"]
    },
    {
      "id": "validate-order",
      "type": "actor",
      "role": "processor",
      "label": "validate_order",
      "handler": "handlers.validate_order",
      "image": "my-image:latest"
    },
    {
      "id": "cond-order-type",
      "type": "router",
      "role": "router",
      "label": "if p['order_type'] == 'express'",
      "condition": "p['order_type'] == 'express'",
      "branches": {
        "true": "express-handler",
        "false": "standard-handler"
      }
    }
  ],
  "edges": [
    {"source": "start-order-processing", "target": "validate-order"},
    {"source": "validate-order", "target": "cond-order-type"},
    {"source": "cond-order-type", "target": "express-handler", "label": "TRUE"},
    {"source": "cond-order-type", "target": "standard-handler", "label": "FALSE"}
  ]
}
```

### 3.3 Node Layout

React Flow supports manual positioning and auto-layout. For DAGs, use
**dagre** (or **ELK.js**) for automatic layered layout (Sugiyama algorithm):

```
npm install dagre  # ~15KB, standard DAG layout
```

Layout is computed once on render, then React Flow handles zoom/pan/drag.

### 3.4 ActorNode Rendering

```
┌──────────────────────────────────┐
│  validate-order-foo-bar     [P]  │  ← K8s actor name + role badge
│  handlers.validate_order         │  ← Python handler path
│  replicas: 3/3  queue: 12       │  ← live data (from provider)
└──────────────────────────────────┘
```

- **Line 1**: Actor name (K8s resource name, e.g., `validate-order-foo-bar`)
  + role badge: [E]ntrypoint, [P]rocessor, [R]outer, [X] exit
- **Line 2**: Handler path (Python module.function)
- **Line 3**: Live status from provider (replicas current/desired, queue depth)

**Border color** reflects actor state:
| State | Border color | Meaning |
|---|---|---|
| Running | Green (#22c55e) | Healthy, processing messages |
| Scaled to zero | Gray (#9ca3af) | Idle, no replicas |
| Error | Red (#ef4444) | Pod crash, OOM, handler error |
| Processing | Blue (#3b82f6) | Currently handling a tracked task |
| Pending | Yellow (#eab308) | Pods starting, pulling image |

**Node fill** reflects role (light tints):
| Role | Fill | Matches DOT |
|---|---|---|
| Entrypoint | Light green (#f0fdf4) | Yes |
| Router (conditional) | Light wheat (#fefce8) | Yes |
| Router (fan-out) | Light blue (#eff6ff) | Yes |
| Processor (user actor) | Light blue (#eff6ff) | Yes |
| Exit | Light green (#f0fdf4) | Yes |

### 3.5 Click Interaction

Clicking a node opens `ActorDetail` in a side panel (or bottom panel in
Jupyter). The detail panel shows:

- **Config**: image, handler, env vars, flavors, transport
- **Status**: replicas (current/desired), pod conditions
- **Queue**: depth, messages in-flight, approximate age of oldest message
- **Logs**: recent log lines from that actor (streamed from provider)

In read-only contexts (prod, Jupyter default), config is display-only. In
write contexts (staging via `asya serve` IDE mode, Phase 4+), config is
editable.

### 3.6 Edge Rendering

| Edge type | Style | Color | Label |
|---|---|---|---|
| Sequential | Solid | Black | — |
| Conditional TRUE | Solid | Green (#16a34a) | "TRUE" |
| Conditional FALSE | Solid | Red (#dc2626) | "FALSE" |
| Fan-out | Solid | Purple (#9333ea) | "slice N" |
| Fan-in | Dashed | Slate (#475569) | — |
| Error/sump | Dashed | Gray (#9ca3af) | — |

---

## 4. Provider Pattern — Data Bridge

### 4.1 Context Interface

```tsx
interface AsyaContextValue {
  // --- Actor data ---
  actors: ActorInfo[];
  getActorStatus(name: string): ActorStatus | null;

  // --- Streaming ---
  subscribeLogs(actorName: string): () => void;  // returns unsubscribe
  logLines: LogLine[];

  // --- Task tracking ---
  taskProgress: TaskProgress | null;
  subscribeTask(taskId: string): () => void;

  // --- Flow metadata ---
  flowName: string;
  context: string;  // k8s-stg, k8s-prod, docker
  readonly: boolean;

  // --- Interactions (host-handled) ---
  onNodeClick?: (nodeId: string) => void;
}

interface ActorInfo {
  name: string;
  handler: string;
  image: string;
  transport: string;
  labels: Record<string, string>;
}

interface ActorStatus {
  replicas: number;
  desiredReplicas: number;
  queueDepth: number;
  state: 'running' | 'scaled-to-zero' | 'error' | 'processing' | 'pending';
  lastError?: string;
}

interface LogLine {
  timestamp: string;
  actor: string;
  level: 'debug' | 'info' | 'warn' | 'error';
  message: string;
}

interface TaskProgress {
  id: string;
  status: string;
  progressPercent: number;
  currentActor: string;
  actorsCompleted: number;
  totalActors: number;
  message: string;
}
```

### 4.2 Data Source: `asya serve` and Direct Python

React components need two kinds of data:

1. **Static**: config, manifests, graph JSON — from local `.asya/` files
2. **Live**: actor status, queue depth, logs — from cluster (kubectl, gateway)

**Source of truth for actor configuration is the XRD manifests** on disk
(`.asya/manifests/<flow>/base/<actor>.yaml`). The manifest path is configured
in `.asya/config.yaml` under `compiler.manifests`. Live cluster state overlays
on top of static manifest data.

Two data paths serve these to React:

#### Path A: `asya serve` (VSCode + standalone web)

`asya serve` is a local FastAPI server that reads `.asya/` and exposes it
via HTTP + WebSocket. It's the single backend for VSCode webview and
standalone web.

```
asya serve (Python, FastAPI)
├── GET  /api/config                         ← merged .asya/config.yaml
├── GET  /api/flows                          ← list compiled flows
├── GET  /api/flows/<flow>/graph             ← graph JSON for React Flow
├── GET  /api/flows/<flow>/manifests         ← XRD manifests (base/common/overlay)
├── PUT  /api/flows/<flow>/manifests/<actor> ← write manifest (non-readonly ctx)
├── GET  /api/actors/<name>/logs             ← kubectl logs (SSE stream)
├── POST /api/flows/<flow>/compile           ← trigger recompilation
├── GET  /api/gateway                        ← gateway URL from context config
├── POST /api/gateway/call                   ← proxy MCP tools/call to gateway
├── GET  /api/gateway/stream/<id>            ← proxy gateway SSE (task progress)
└── WS   /ws/actors                          ← WebSocket: live actor status
```

**K8s Python SDK (not kubectl)**: `asya serve` uses the `kubernetes` Python
client library directly — no subprocess spawning. Benefits:
- Native **watch API**: `watch.Watch().stream()` on AsyncActor resources.
  One persistent connection to the K8s API server pushes all changes.
- Connection pooling, proper auth (kubeconfig or in-cluster service account)
- Works with in-cluster config when running inside K8s (asya-lens)

**WebSocket for actor status** (`/ws/actors`): `asya serve` watches
AsyncActor resources via K8s watch API and fans out changes to connected
WebSocket clients. One watch per resource type, one WebSocket per browser
tab, multiplexed. Client subscribes to actors it cares about:

```json
// Client → Server: subscribe
{"subscribe": ["validate-order-foo-bar", "express-handler-foo-bar"]}

// Server → Client: status change (pushed instantly)
{"actor": "validate-order-foo-bar", "status": {
  "replicas": 3, "desiredReplicas": 3,
  "queueDepth": 12, "state": "running"
}}
```

No polling — the K8s watch API pushes events in milliseconds.

**SSE for task streaming**: Gateway task progress (`/mesh/{id}/stream`) is
already SSE — `asya serve` proxies it. The gateway's `/mesh/*` endpoints
are cluster-internal (sidecar progress reporting) — `asya serve` proxies
via the external gateway URL (`contexts.<name>.gateway`). User-facing calls
use MCP (`tools/call`) or A2A (`message/send`) protocol.

`readonly: true` contexts (prod) reject all PUT/POST requests. The API
enforces the read/write boundary — React components don't need to know
which context is readonly.

**VSCode**: extension starts `asya serve` as a subprocess. Webview panel
connects to `localhost:<port>`. Extension host manages lifecycle (start on
activate, stop on deactivate).

**Standalone web**: `asya serve` serves both the API and the bundled
`@asya/ui` SPA as static files.

#### Path B: Direct Python (Jupyter)

In Jupyter, the magic runs in the same Python process as the notebook.
No HTTP server needed — `asya_lab` functions are called directly:

```python
from asya_lab.project import load_config
from asya_lab.compile import compile_flow

config = load_config()          # reads .asya/config.yaml
graph = compile_flow("order")   # returns graph JSON
manifests = read_manifests("order")  # reads XRD YAML files
```

The Python side pushes data to the anywidget model. For live data (status,
logs), the Python side uses the K8s Python SDK watch API directly and pushes
to the model.

### 4.3 Provider Implementations

Two providers, same `AsyaContextValue` interface:

#### HTTP + WebSocket Provider (VSCode + standalone web)

```tsx
function HttpAsyaProvider({ baseUrl, children }) {
  // REST:
  //   GET /api/flows/<flow>/manifests → actors[] (initial load)
  //   GET /api/actors/<name>/logs     → SSE → logLines[]
  //   GET /api/gateway/stream/<id>    → SSE → taskProgress
  //   PUT /api/flows/<flow>/manifests/<actor> → write (if !readonly)
  //
  // WebSocket:
  //   WS /ws/actors → subscribe to actor status changes (K8s watch)
  //   Replaces polling — instant updates on scale, crash, state change
}
```

Single `baseUrl` prop — points to `asya serve` at `localhost:<port>`.
WebSocket connection opens on mount, subscribes to visible actors.

#### Anywidget Provider (Jupyter)

```tsx
function AnywidgetAsyaProvider({ model, children }) {
  // model.get('actors')       → actors[]
  // model.get('status')       → Map<name, ActorStatus>
  // model.on('change:logs')   → logLines[]
  // model.on('change:task')   → taskProgress
}
```

Python side sets model attributes; React side reacts to changes.
No HTTP — data flows through anywidget's traitlets sync mechanism.

### 4.4 Complexity Assessment

| Piece | Lines (approx.) | Complexity |
|---|---|---|
| Context definition + hook | ~50 | Trivial — React boilerplate |
| HTTP provider (web + VSCode) | ~120 | Standard — fetch + EventSource |
| Anywidget provider (Jupyter) | ~80 | Simple — model.on('change:*') |
| Type definitions | ~60 | Trivial — interfaces |
| `asya serve` API routes | ~300 | Standard FastAPI (reads files, proxies kubectl) |
| **Total (React side)** | **~310** | **Low** |

Components stay pure and testable — mock the provider for unit tests.

---

## 5. Anywidget Integration (Jupyter)

### 5.1 How Anywidget Works

anywidget bridges Python ↔ JavaScript in Jupyter notebooks:

```python
# Python side
import anywidget
import traitlets

class FlowWidget(anywidget.AnyWidget):
    _esm = "flow_widget.js"          # JS bundle (React app)
    _css = "flow_widget.css"         # Styles

    # Synced state (Python ↔ JS, bidirectional)
    graph = traitlets.Dict({}).tag(sync=True)
    actors = traitlets.List([]).tag(sync=True)
    status = traitlets.Dict({}).tag(sync=True)
    selected_node = traitlets.Unicode("").tag(sync=True)
```

```js
// JS side (flow_widget.js)
export function render({ model, el }) {
  const root = createRoot(el);
  root.render(
    <AnywidgetAsyaProvider model={model}>
      <FlowDiagram graph={model.get('graph')} />
    </AnywidgetAsyaProvider>
  );

  // React to Python-side changes
  model.on('change:status', () => {
    // Provider re-renders components automatically
  });
}
```

### 5.2 Jupyter Magic Integration

```python
# asya_lab/jupyter/magics.py

@line_magic
def asya(self, line):
    args = shlex.split(line)
    if args[0] == 'compile':
        graph = compile_flow(args[1])
        widget = FlowWidget(graph=graph)
        display(widget)

    elif args[0:2] == ['k', 'status']:
        actors = kubectl_get_actors(args[2])
        widget = StatusWidget(actors=actors)
        # Background task updates widget.status periodically
        display(widget)
```

### 5.3 Bundle Size Considerations

| Dependency | Size (minified + gzip) |
|---|---|
| React + ReactDOM | ~45KB |
| React Flow | ~30KB |
| dagre (layout) | ~15KB |
| @asya/ui components | ~20KB (estimate) |
| **Total widget bundle** | **~110KB** |

Acceptable for Jupyter — widgets load once per notebook session. The bundle
is embedded in the Python package (`asya-lab[jupyter]`), no CDN dependency.

---

## 6. VSCode Extension Integration

### 6.1 Webview Panel Architecture

```
┌──────────────────────────────────────────────────┐
│  VSCode Extension Host (Node.js)                 │
│  ┌───────────────────┐                           │
│  │ asya serve        │ ← starts as subprocess    │
│  │ (localhost:PORT)   │                           │
│  └────────┬──────────┘                           │
│           │ HTTP / SSE / WebSocket               │
│  ┌────────▼──────────────────────────────────┐   │
│  │  Webview Panel (iframe)                   │   │
│  │  ┌────────────────────────────────────┐   │   │
│  │  │  HttpAsyaProvider baseUrl=:PORT    │   │   │
│  │  │  ┌────────────────────────────┐    │   │   │
│  │  │  │  FlowDiagram               │    │   │   │
│  │  │  │  ActorDetail               │    │   │   │
│  │  │  │  LogViewer                 │    │   │   │
│  │  │  └────────────────────────────┘    │   │   │
│  │  └────────────────────────────────────┘   │   │
│  └───────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

The webview uses the same `HttpAsyaProvider` as the standalone web app —
it talks directly to `asya serve` via HTTP. No `postMessage` bridge needed
for data. The extension host's only jobs are:

1. Start `asya serve` as a subprocess on activate
2. Stop `asya serve` on deactivate
3. Handle VSCode-specific actions (open files, navigate to source)

### 6.2 Extension Host Responsibilities

The extension host is thin — `asya serve` does the heavy lifting:

1. **Lifecycle**: start/stop `asya serve` subprocess, pick free port
2. **VSCode actions**: handle webview click events that need VSCode APIs
   (opening files, showing notifications, navigating to source code)
3. **Port forwarding**: if webview can't reach localhost directly (remote
   development), extension host proxies requests

The webview iframe connects to `asya serve` directly for all data. No
serialization through `postMessage` for data — only for VSCode-specific
actions (open file, show dialog).

### 6.3 VSCode-Specific Interactions

| User action | Mechanism | Response |
|---|---|---|
| Click actor node | HTTP: `GET /api/actors/<name>` | `ActorDetail` renders in side panel |
| Click "Open Config" | postMessage → extension host | `vscode.workspace.openTextDocument()` |
| Click "View Logs" | HTTP: `GET /api/actors/<name>/logs` (SSE) | `LogViewer` streams inline |
| Edit manifest | HTTP: `PUT /api/flows/<flow>/manifests/<actor>` | `asya serve` writes to disk |
| Click "Scale" | Deferred to Phase 4+ | — |

Only "Open Config" needs `postMessage` (VSCode API). Everything else goes
through `asya serve` HTTP.

---

## 7. Static Output — Graphviz (Separate Path)

Static PNG/SVG output is NOT rendered by React Flow. It uses the existing
Graphviz DOT pipeline:

```
Compiler → DOT file → graphviz CLI → PNG/SVG
```

**Why two rendering paths**: React Flow gives rich interactivity (click, zoom,
live data), but requires a JS runtime. Static output must work in CI, docs,
GitHub README, nbviewer — contexts where JS can't run. Graphviz produces
deterministic, portable images.

**CLI flags**:
- `asya flow compile --plot` → DOT + PNG (default format)
- `asya flow compile --plot --format svg` → DOT + SVG
- `asya flow compile --plot --format dot` → DOT only (no rendered image)

**Output location**: `.asya/flows/plots/<flow>/` (configurable via
`config.plots.dir`).

**Visual parity**: The DOT generator and React Flow use the same color
conventions (green for entrypoints, wheat for conditionals, blue for actors)
so static and interactive views look consistent, even though layouts differ
(Sugiyama in both, but different implementations).

---

## 8. Design Tokens and Theming

### 8.1 Status Colors

```ts
export const STATUS_COLORS = {
  running:       { border: '#22c55e', bg: '#f0fdf4' },  // green
  'scaled-to-zero': { border: '#9ca3af', bg: '#f9fafb' },  // gray
  error:         { border: '#ef4444', bg: '#fef2f2' },  // red
  processing:    { border: '#3b82f6', bg: '#eff6ff' },  // blue
  pending:       { border: '#eab308', bg: '#fefce8' },  // yellow
} as const;
```

### 8.2 Role Colors (Node Fill)

```ts
export const ROLE_COLORS = {
  entrypoint: '#f0fdf4',  // light green
  exitpoint:  '#f0fdf4',  // light green
  router:     '#fefce8',  // light wheat (conditional)
  fanout:     '#eff6ff',  // light blue
  processor:  '#eff6ff',  // light blue
} as const;
```

### 8.3 Log Level Colors

```ts
export const LOG_COLORS = {
  debug: '#9ca3af',  // gray
  info:  '#3b82f6',  // blue
  warn:  '#eab308',  // yellow
  error: '#ef4444',  // red
} as const;
```

Colors match the DOT generator output for visual consistency.

---

## 9. Testing Strategy

### 9.1 Component Tests

```bash
npm test                    # Vitest + React Testing Library
```

Components are tested with a mock provider:

```tsx
function renderWithMock(ui, overrides = {}) {
  const mockContext = {
    actors: [{ name: 'test-actor', handler: 'mod.fn', ... }],
    getActorStatus: () => ({ replicas: 3, state: 'running', ... }),
    logLines: [],
    ...overrides,
  };
  return render(
    <AsyaContext.Provider value={mockContext}>{ui}</AsyaContext.Provider>
  );
}

test('ActorNode shows replica count', () => {
  renderWithMock(<ActorNode id="test-actor" />);
  expect(screen.getByText('3')).toBeInTheDocument();
});
```

### 9.2 Visual Regression

Storybook stories for each component + Chromatic (or Percy) for visual
regression testing. Each component has stories for all states (running,
error, scaled-to-zero, etc.).

### 9.3 Integration Tests

Each host provider is tested with its real transport:
- Web provider: MSW (Mock Service Worker) for HTTP/SSE
- VSCode provider: mock `postMessage` API
- Anywidget provider: mock traitlets model

---

## 10. Build and Distribution

### 10.1 Build Pipeline

```
@asya/ui (npm package)
├── src/                     # React components + provider interface
├── dist/                    # ESM + CJS bundles (tsc + rollup/vite)
├── package.json
└── tsconfig.json

Consumers bundle @asya/ui into their output:
├── asya-lab[jupyter]        # Vite → single JS bundle → embedded in Python wheel
├── asya-vscode              # VSCode webview → bundled with extension
└── asya-lab[ui]             # Vite → SPA → served by asya serve
```

### 10.2 Dependency Policy

`@asya/ui` has minimal dependencies:
- `react`, `react-dom` — peer dependency
- `@xyflow/react` (React Flow) — direct dependency
- `dagre` — direct dependency (layout)

No UI framework (no MUI, no Ant Design, no Tailwind). Components use CSS
modules or vanilla CSS. Keeps the bundle small and avoids framework lock-in.

---

## 11. Resolved Questions

1. ~~**Graph JSON emission**~~: **Resolved**. Always emit graph JSON alongside
   DOT (~5KB, negligible). Additionally, always render PNG to the configured
   plots directory (`config.plots.dir`, default `.asya/flows/plots/`) — keeps
   a gallery of all flow graphs on disk. In interactive environments (Jupyter,
   VSCode), show the interactive React Flow widget by default. Static PNG is
   always available as a fallback and for CI/docs/README.

2. ~~**Live status polling interval**~~: **Resolved**. No polling — WebSocket
   backed by K8s watch API pushes actor status changes instantly. See §4.2.

3. ~~**Storybook hosting**~~: **Resolved**. Local-only (`npm run storybook`).
   Storybook is a component catalog for developing and reviewing UI components
   in isolation. Local is sufficient for a small team. Add GitHub Pages
   hosting later if non-developers need to review visual designs.

4. ~~**Accessibility**~~: **Resolved**. ARIA labels from day one. Colors are
   supplementary — state must be distinguishable without color (role badges,
   border patterns). React Flow provides keyboard navigation out of the box.

5. ~~**Dark mode**~~: **Resolved**. Ship dark theme from start. VSCode users
   expect it. Use CSS custom properties for all design tokens — light/dark
   switch is just swapping token values.

## 12. Resolved Questions (continued)

6. ~~**`asya serve` port management**~~: **Resolved**. Dynamic port selection
   from an ephemeral range. `asya serve` picks a free port, prints it to
   stdout on startup (e.g., `Listening on http://localhost:54321`). VSCode
   extension parses stdout to discover the port. `--port` flag for explicit
   override. No lockfile needed — stdout is the discovery mechanism.

7. ~~**`asya serve` authentication**~~: **Resolved (deferred)**. Localhost-only
   for now — bind to `127.0.0.1`, no auth. When asya-lens runs on shared
   servers, add token-based auth (bearer token generated on startup, printed
   to stdout alongside port). Tracked as future security hardening task.

8. ~~**Graph JSON vs DOT layout divergence**~~: **Resolved (deferred)**.
   Implement dagre layout first, evaluate visually against existing
   `examples/flows/**/*.py` compiled graphs. If dagre output is acceptable,
   keep two independent layout engines. If not, consider layout hints in
   graph JSON. Decision after visual comparison.
