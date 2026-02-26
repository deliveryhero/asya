---
title: Client CLI, Python SDK, and Jupyter Magics
priority: 1 # high
type: epic
dependencies: [1jow]
---

Foundation layer for all Asya client surfaces. Refactor the existing `asya-cli` into an importable Python SDK (`asya` package) with a thin CLI wrapper, Jupyter magic functions, and a local HTTP server for UI surfaces.

## Scope

- Python SDK (`asya` package) with extras: `[ui]`, `[jupyter]`, `[deploy]`, `[all]`
- CLI organized by domain abstractions: `asya flow`, `asya actor`, `asya msg`, `asya context`
- Jupyter magic functions (`%asya`) with interactive flow visualization
- Layered compiler: frontends (simplified YAML, CRD, Flow DSL) to IR (manifest.yaml) -- backends are external
- Project configuration: `asya.yaml` with contexts, `actorDefaults`, dotenv resolution
- Context system (like kubectl): k8s-stg, k8s-prod, docker -- overridable by ASYA_CONTEXT env var
- `asya serve`: local HTTP/WS server for VSCode extension and standalone web
- Refactoring from existing asya-cli (~3,400 lines)

## Milestone 1: SDK + CLI (First Deliverable)

This epic is the first milestone because it unblocks all other client surfaces:
- Jupyter magics import SDK functions directly
- VSCode extension talks to `asya serve` (part of SDK)
- Standalone web uses the same `asya serve`

## Key Design Decisions

- CLI is a thin wrapper -- every command maps 1:1 to an SDK function
- Protocol (MCP/A2A) hidden from DS -- `--protocol` flag for rare cases, gateway handles the rest
- `asya flow logs` displays with colorful actor-name prefix (like docker compose)
- Deploy/undeploy verbs (not up/down) for K8s safety
- All asya.yaml values overridable by ASYA_* env vars and --options

## Related Epics

- 1jow: Client UX Design (parent design document)
- 1juv: VSCode Extension and Standalone Web (depends on this epic)
- 1is3: GitOps Flow Design (project structure and compilation)
- 1ibt: Design client commands deploy/undeploy (existing design work)
- 1g2t: Gateway dynamic tool exposure via CLI
