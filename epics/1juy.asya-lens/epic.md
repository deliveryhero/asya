---
title: "Asya Lens: Self-Hosted Dashboard and IDE"
priority: 2 # medium
type: epic
dependencies: [1jux, 1juv]
---

Single Docker image (`asya-lens`) that serves as both a shared status dashboard and
a self-hosted development environment. Built on code-server with the Asya VSCode
extension and `asya-lab[ui]` pre-installed.

## Scope

- Docker image: `asya-lens` (GHCR)
- Base: code-server (self-hosted VSCode in the browser)
- Bundled: Asya VSCode extension (`.vsix`), `asya-lab[ui,deploy]`, kubectl, helm
- Two usage modes:
  - **Dashboard mode**: shared status display (wall monitor, CI, ops team)
  - **IDE mode**: full development environment for data scientists
- Helm chart for K8s deployment
- Context-aware via ASYA_CONTEXT

## Image Naming Decision

`asya-lens` was chosen because:
- Practical: a lens is something you look through to observe
- Works for both modes: looking at status (dashboard) and into code (IDE)
- Short and memorable

Rejected alternatives: `asya-dashboard` (undersells IDE capability),
`asya-studio`/`asya-console` (user preference), `asya-workbench` (generic).

## Architecture

- code-server provides the browser-based VSCode environment
- The VSCode extension spawns `asya serve` internally (same as local VSCode)
- `asya serve` provides the REST/WebSocket API for all UI operations
- In dashboard mode, users access the web UI panels directly
- In IDE mode, users get the full code-server experience with Asya integration
- Same image, same entry point -- usage determines the experience

## Related Epics

- 1jux: Asya Lab -- Python SDK packaged inside this image
- 1juv: Asya UI -- VSCode extension and React components bundled here
- 1jow: Client UX Design (parent design document)
