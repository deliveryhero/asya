---
title: Client UX Design - Asya Developer Experience
priority: 1 # high
type: epic
---

Unified developer experience across CLI, Jupyter, VSCode, and standalone web
for interacting with Asya actor meshes. This is the master design document
that all other client epics reference.

The core principle is a single Python SDK (`asya` package) as the source of
truth for all logic. Every surface -- CLI, Jupyter magics, VSCode extension,
standalone web -- is a thin wrapper that calls into the SDK. State lives in
local files (`asya.yaml`, `actor.yaml`, `.env`) that are all git-committable,
enabling a lab-to-prod GitOps workflow where data scientists iterate
imperatively in staging and promote declaratively to production via PR review.

## Scope

- Python SDK architecture and package layout
- Layered compiler (frontends -> IR -> backends)
- Actor identity model (code-as-actor-card)
- Project structure conventions (`src/` + `deploy/`)
- CLI command taxonomy (flow, actor, msg)
- Environment variable and config management
- `asya.yaml` project configuration
- UI surfaces: Jupyter magics, VSCode extension, standalone web
- GitOps workflow (lab mode vs prod mode)
- Local testing with Docker Compose
- Shadow / plug-in-local actor support

## Related Epics

- 1jpc: Client CLI and SDK (implementation)
- 1juv: VSCode Extension and Standalone Web
- 1is3: GitOps Flow Design
- 1iqd: Flow Workflow Design (ADR: labels vs CRD)
- 1ibt: Client Commands deploy/undeploy
- 1crb: Traffic Routing (shadow/plug-in-local)
- 1c0d: A2A Protocol Compliance
- 1g2t: Gateway Dynamic Tool Exposure
- 1iu4: Local Testing Workflow
- 1iu5: Seamless Experimentation Image Building
