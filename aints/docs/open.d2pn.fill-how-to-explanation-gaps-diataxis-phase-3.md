---
title: Fill how-to and explanation gaps (Diataxis Phase 3)
priority: 3 # low
dependencies:
  - zb3d
---

Fill remaining Diataxis gaps in how-to guides and explanation docs.

How-to guides to write:
1. `howto/add-new-actor.md` — Write handler, create AsyncActor manifest, deploy, verify
2. `howto/debug-envelope.md` — Trace an envelope through the mesh (logs, metrics, curl sidecar)
3. `howto/register-gateway-tools.md` — Extract from architecture/asya-gateway.md

Explanations to write:
1. `explanation/choreography-vs-orchestration.md` — Why choreography; trade-offs vs LangGraph/CrewAI
2. `explanation/envelope-design.md` — Why route.prev/curr/next; why immutable IDs; why payload is opaque

Reference to consolidate:
1. `reference/env-vars.md` — Consolidated env var reference across all components
2. `reference/asyncactor-crd.md` — Full CRD field reference

See parent aint u1zh for full audit context.
