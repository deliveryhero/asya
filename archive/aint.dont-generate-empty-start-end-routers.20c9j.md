---
title: Don't generate empty start/end routers
status: rejected
priority: 2
tags:
  - superseded-by:gml9
---

## Problem

The compiler always generates start and end routers for every flow, even when
they do nothing (no mutations, no conditional routing). A single-actor flow
like `def my_flow(p): p = handler(p); return p` produces three actors
(start-router, handler, end-router) when only one is needed.

## Design

Skip router generation when the router would be a no-op:

- **Start router**: skip if no initial mutations and flow starts with a single
  actor call (just route directly to the first actor)
- **End router**: skip if no final mutations and the last actor's output goes
  directly to sink (just let the last actor be the exitpoint)

The grouper already knows what operations each router contains. Add a check:
if a router's operation list is empty (no mutations, no conditionals), elide it
from the output and adjust routing accordingly.

## Edge cases

- Single-actor flow: `p = handler(p)` → no routers at all, just the actor
- Flow with only mutations: `p["x"] = 1; return p` → one mutation router, no actors
- Flow where start has mutations but end doesn't → keep start, skip end

## References

- `.aint/aints/asya-lab/rfc.md` §8 — three-layer kustomize structure (routers
  are generated into `base/`)
- `src/asya-cli/asya_cli/flow/grouper.py` — router grouping logic
- `src/asya-cli/asya_cli/flow/codegen.py` — router code generation
