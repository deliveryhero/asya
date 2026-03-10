---
title: "Asya Lens: Self-Hosted Dashboard and IDE"
priority: 2
---

Single Docker image (`asya-lens`) that serves as both a shared status dashboard
and a self-hosted development environment. Built on code-server with the Asya
VSCode extension and `asya-lab[ui,deploy]` pre-installed.

## Scope

- Docker image: `asya-lens` (GHCR), based on code-server
- Bundled: Asya VSCode extension (`.vsix` from `src/asya-lab/ui/`),
  `asya-lab[ui,deploy]` wheel, kubectl, helm
- Two usage modes:
  - **Dashboard mode**: read-only status display (wall monitor, ops team)
  - **IDE mode**: full development environment for data scientists (PVC)
- Helm chart for K8s deployment (`deploy/helm-charts/asya-lens/`)
- Context-aware via `.asya/config.yaml` (walk-up resolution, in-cluster config)
- `asya serve` uses K8s Python SDK with in-cluster config for live status

## Related Epics

- asya-lab: Python SDK, CLI, `asya serve` backend packaged inside this image
- asya-ui: `@asya/ui` React components and VSCode extension bundled here
