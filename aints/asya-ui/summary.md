---
title: "Asya UI: TypeScript Workspace (React Components + VSCode Extension)"
priority: 3 # low
---


TypeScript pnpm monorepo workspace containing all client-side UI code: the shared
React component library (`@asya/ui`) and the VSCode extension. Both packages live
under `src/asya-ui/` with separate build outputs.

## Scope

- pnpm workspace at `src/asya-ui/` with two packages:
  - `packages/components/` -- `@asya/ui` React component library
  - `packages/vscode/` -- VSCode extension (`.vsix`)
- Shared tooling: tsconfig, eslint, prettier, vitest
- React components: FlowDiagram, ActorCard, LogViewer, StatusDashboard, ConfigEditor
- VSCode extension: spawns `asya serve`, relays postMessage to HTTP/WS, registers commands
- Build pipeline: React bundle output goes into `asya-lab[ui]` static assets; `.vsix` goes into asya-lens Docker image

## Distribution

| Package | Channel | Consumer |
|---|---|---|
| `@asya/ui` | Bundled as static assets into `asya-lab[ui]` | Standalone web SPA, VSCode webviews |
| VSCode extension | VS Code Marketplace (for local users) | Local VSCode installs |
| VSCode extension | Bundled into `asya-lens` Docker image | Self-hosted code-server |

## Architecture

- Extension host (TypeScript) manages `asya serve` lifecycle and relays postMessage between sandboxed webviews and the Python server
- React webviews have no direct Python/filesystem access
- `@asya/ui` components are framework-agnostic React -- consumed by both VSCode webviews and the standalone web SPA
- `asya serve` is context-aware: shows data from current ASYA_CONTEXT

## Related Epics

- 1jow: Client UX Design (parent design document)
- 1jux: Asya Lab -- Python SDK and CLI (provides `asya serve` backend)
- 1juy: Asya Lens -- Docker image that bundles extension + SDK for self-hosting
- 1jpc: Client CLI (predecessor; detailed CLI/SDK API design)
