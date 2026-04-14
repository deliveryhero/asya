---
title: "Phase 6: @asya/ui React components + asya serve + Jupyter widget"
status: working
priority: 2
assignee: Artem Yushkovskiy
dependencies:
  - 5ifn
  - 4g10
tags:
  - worktree:.worktrees/.worktrees/asya-lab/e4u9.phase-6-asya-ui-react-components-asya-serve
  - branch:asya-lab/e4u9.phase-6-asya-ui-react-components-asya-serve
---

Design doc: `rfc-ui-components.md` (same epic).

## Scope

Implement the interactive UI layer: `@asya/ui` React component library,
`asya serve` FastAPI backend, anywidget Jupyter integration, and the
build pipeline that ties them together.

## Deliverables

### 6a. Scaffold `src/asya-lab/ui/`

- `package.json` (`@asya/ui`), `tsconfig.json`, Vite config
- Directory structure: `src/components/`, `src/providers/`, `src/tokens/`,
  `src/widgets/`
- Storybook setup (`npm run storybook`)
- `make build` target in `src/asya-lab/Makefile` chaining `npm run build` + `uv build`

### 6b. Graph JSON emission from compiler

- Extend compiler to emit `graph.json` alongside `flow.dot`
- Two-axis node schema: `type` (router/actor) + `role` + `entrypoint`/`exitpoint` flags
- 5 edge types: `sequential`, `true`, `false`, `except`, `fanout`
- Groups for try/finally blocks
- JSON saved to `.asya/flows/<flow>/graph.json`

### 6c. Core React components (Phase 3 set)

- `FlowDiagram` — React Flow wrapper, dagre layout, zoom/pan/minimap
- `ActorNode` — custom node: actor name, handler path, live status,
  role badge, type-based fill (wheat/blue), entry/exit thick border
- `ActorDetail` — side panel: config summary, replicas, queue depth, logs
- `LogViewer` — streaming log lines with actor-name coloring
- `TaskProgress` — progress bar with current actor
- `StatusBadge` — inline status indicator
- Design tokens: `STATUS_COLORS`, `TYPE_COLORS`, `LOG_COLORS` (light + dark)
- CSS custom properties for dark mode

### 6d. Provider pattern + `AsyaContext`

- `AsyaContextValue` interface + `useAsya()` hook
- `ConnectionState` type (`connecting`/`connected`/`reconnecting`/`degraded`/`error`)
- Mock provider for Storybook and unit tests
- `HttpAsyaProvider` (for web/VSCode — talks to `asya serve`)
- `AnywidgetAsyaProvider` (for Jupyter — traitlets model sync)

### 6e. `asya serve` (FastAPI backend)

- `.asya/` walk-up project discovery (§4 of rfc-ui-components.md)
- Config merge (nearest wins, parents inherited read-only)
- REST routes: `/api/config`, `/api/flows`, `/api/flows/<flow>/graph`,
  `/api/flows/<flow>/manifests`, `/api/flows/<flow>/compile`
- Gateway proxy: `/api/gateway/call`, `/api/gateway/stream/<id>` (SSE)
- Actor logs: `/api/actors/<name>/logs` (SSE, K8s Python SDK)
- WebSocket `/ws/actors` — K8s watch API fan-out for live actor status
- `readonly` enforcement (reject PUT/POST when `readonly: true`)
- Dynamic port selection, print to stdout
- Serve `@asya/ui` SPA as static files

### 6f. Anywidget Jupyter integration

- `FlowWidget(anywidget.AnyWidget)` with traitlets: graph, actors, status
- `flow_widget.tsx` entry point (Vite library mode build)
- Build pipeline: `npm run build:widget` → `asya_lab/static/flow_widget.js`
- `pyproject.toml` package-data for `static/*.js`, `static/*.css`
- `.gitignore` for built JS (built in CI, not committed)
- `%asya compile <flow>` magic renders interactive widget

### 6g. Testing

- Vitest + React Testing Library for component tests (mock provider)
- Storybook stories for each component (all states)
- `asya serve` unit tests (FastAPI TestClient)
- WebSocket + SSE integration tests (mock K8s watch)

### 6h. CI and publishing

- GitHub Actions workflow: `npm ci && npm run build && npm test && npm run lint`
  in `src/asya-lab/ui/`
- Widget bundle build (`npm run build:widget`) before `uv build` in the
  existing asya-lab publish workflow
- `asya-lab[jupyter]` wheel includes built JS in `asya_lab/static/`
- `@asya/ui` published to npm (or GitHub Packages) on tag — same version
  as `asya-lab` Python package (one tag, one release workfklow, both publish)
- `asya-lab[ui]` SPA bundle served by `asya serve` from `ui/dist/`
- Pre-commit: add `npm run lint` + `npm run typecheck` for `src/asya-lab/ui/`

## Out of scope (later phases)

- VSCode extension (asya-lens epic, separate build)
- Phase 4 components: StatusDashboard, ActorCard, ToolBrowser, ConfigEditor
- Manifest editing via PUT API (Phase 4+)
- Auth for `asya serve` (deferred, localhost-only for now)
- ELK.js layout alternative (dagre first, evaluate later)
