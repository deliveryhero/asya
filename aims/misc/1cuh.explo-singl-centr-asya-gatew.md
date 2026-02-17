---
title: Explore single central asya-gateway vs per-namespace gateways
status: open
priority: 3 # low
type: task
---

## Problem Statement

Currently, asya-gateway is deployed per-namespace. This creates:
1. **Maintenance burden** - Each namespace needs its own gateway deployment
2. **User friction** - Data Science teams don't want to maintain public gateways in their clusters
3. **Resource overhead** - Multiple gateway instances across namespaces

## Proposed Alternative

Consider a **single central asya-gateway** in asya-system namespace serving all namespaces.

## Requirements to Explore

If implementing central gateway:
1. **Namespace separation** - Gateway must route to correct namespace's actors
2. **RBAC implementation** - Users should only access their namespace's tools/actors
3. **Multi-tenancy** - Envelope isolation between namespaces
4. **Authentication/Authorization** - How to identify and authorize callers per namespace

## Questions to Answer

- How do MCP tools map to namespaces? (tool naming, discovery)
- What's the RBAC model? (K8s RBAC, custom auth, API keys per namespace?)
- How does queue naming work across namespaces? (already prefixed: asya-{namespace}-{actor})
- Performance implications of single gateway vs distributed?
- Failure domain considerations?

## Acceptance Criteria

- [ ] Document pros/cons of both approaches
- [ ] Design RBAC/auth model if central gateway chosen
- [ ] Prototype or proof-of-concept if needed


---
_Migrated from beads `asya-55z`_
