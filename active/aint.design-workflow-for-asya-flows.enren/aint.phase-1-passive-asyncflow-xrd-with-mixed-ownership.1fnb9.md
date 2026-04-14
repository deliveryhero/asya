---
title: "Phase 1: Passive AsyncFlow XRD with mixed ownership model"
status: open
priority: 1
tags:
  - type:feature
---

Outdated? see ADR.



Design and implement AsyncFlow as a Crossplane XRD that:

1. Schema:
   - spec.processors: list of actor names (referenced only, not created)
   - spec.routers: list of {actor, handler} entries (created by composition)
   - spec.routerCode / spec.routerCodeRefs: inline code or existing ConfigMap references (mutually exclusive)
   - spec.expose: optional MCP tool exposure config (tool name, description, parameters, route)
   - spec.transport: transport type for created router actors

2. Composition creates:
   - Router AsyncActor claims (owned) with routers.py ConfigMap mounted
   - ConfigMap(s) with router code (owned, from spec.routerCode)
   - OR observes existing ConfigMaps (from spec.routerCodeRefs, managementPolicies: Observe)

3. Naming:
   - Kind: AsyncFlow, plural: asyncflows, shortNames: [asyf]
   - API group: asya.sh (user-facing)

4. Labels:
   - Created routers get asya.sh/flow=<flow-name> label
   - Created routers get asya.sh/actor-type=router label
   - Processors referenced by name only (no labels managed by AsyncFlow)

Dependencies: Requires spec.actor field on AsyncActor XRD (asya-v2hs)


_Migrated from beads `asya-qyzk`_
