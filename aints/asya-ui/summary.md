---
title: "@asya/ui: React Component Library & UI Architecture"
priority: 2
---

Shared React component library (`@asya/ui`) consumed by Jupyter (anywidget),
VSCode extension (webview panels), and `asya serve` (standalone web SPA).
Source lives at `src/asya-lab/ui/`, colocated with the Python package.

## Scope

- `@asya/ui` React components: FlowDiagram (React Flow), ActorNode, ActorDetail,
  LogViewer, TaskProgress, StatusBadge, StatusDashboard, ConfigEditor
- Provider pattern: `AsyaContextValue` interface with two implementations
  (HTTP+WebSocket for web/VSCode, anywidget traitlets for Jupyter)
- `asya serve` API design (FastAPI, K8s Python SDK, WebSocket for actor status)
- Graph JSON schema (two-axis node classification, 5 edge types)
- Project discovery (`.asya/` walk-up resolution with config inheritance)
- VSCode extension architecture (thin host, webview talks directly to `asya serve`)
- Anywidget JS bundle → Python wheel pipeline (Vite → static/ → wheel)
- Design tokens, theming (dark mode from day one), accessibility (ARIA)

## Related Epics

- asya-lab: Python SDK, CLI, `asya serve` backend
- asya-lens: Docker image bundling extension + SDK for self-hosting
