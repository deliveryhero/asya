---
title: "Asya Lab: Python SDK, CLI, and Jupyter Magics"
priority: 1 # high
---


Python package `asya-lab` (PyPI) -- the single source of truth for all Asya client
logic. Every CLI command maps 1:1 to an SDK function. Jupyter magics call the SDK
directly. The VSCode extension and standalone web talk HTTP to `asya serve` (part
of this package). React components (TypeScript) are visuals only -- no business
logic lives in TypeScript.

## Scope

- Package name: `asya-lab` (PyPI, since `asya` is taken)
- Extras: `[ui]` (FastAPI server + bundled React SPA), `[jupyter]` (magics),
  `[deploy]` (kubectl/helm wrappers), `[all]`
- CLI organized by domain abstractions: `asya flow`, `asya actor`, `asya msg`, `asya context`
- Layered compiler: frontends (simplified YAML, CRD, Flow DSL) to IR (manifest.yaml)
- Project configuration: `asya.yaml` with contexts, dotenv resolution
- Context system: k8s-stg, k8s-prod, docker -- overridable by ASYA_CONTEXT
- `asya serve`: local HTTP/WS server for VSCode extension and standalone web
- Jupyter magics with interactive flow visualization
- `asya.testing`: pytest fixtures for VFS and state mocking
- Migration from existing `asya-cli` (~3,400 lines)

## Package Naming Decision

`asya` is taken on PyPI. `asya-lab` was chosen because:
- Practical and DS-native (data scientists work in labs)
- Signals experimentation, compilation, and tooling
- Short and memorable (`pip install asya-lab`)
- No ambiguity about purpose

Rejected alternatives: `asya-sdk` (generic), `asya-client` (generic),
`asya-stage` (theater-themed, less practical), `asya-plants`/`asya-stooge`
(niche theater references, confusing).

## Key Design Decisions

- CLI is a thin wrapper -- every command maps 1:1 to an SDK function
- React SPA from `@asya/ui` is bundled as static assets into `asya-lab[ui]`
- Protocol (MCP/A2A) hidden from DS -- `--protocol` flag for rare cases
- Deploy/undeploy verbs (not up/down) for K8s safety
- All asya.yaml values overridable by ASYA_* env vars and --options

## Related Epics

- 1jow: Client UX Design (parent design document)
- 1jpc: Client CLI (predecessor; detailed CLI/SDK API and migration design)
- 1juv: Asya UI -- TypeScript workspace (depends on this for `asya serve` backend)
- 1juy: Asya Lens -- Docker image that includes this package
