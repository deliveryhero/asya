---
title: Explore single central asya-gateway vs per-namespace gateways
status: done
priority: 3 # low
type: task
tags:
  - type:feature
reason: "Decided: per-namespace gateway for simplicity, security isolation, and throughput guarantees. ADR added to 1fc44c."
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

## ADR: Per-Namespace Gateway (Decision)

**Status**: Accepted (2026-02-23)

**Decision**: Keep per-namespace gateway deployment. Do not pursue central gateway or custom load balancing.

**Rationale**:

1. **Simplicity** -- per-namespace is the Kubernetes-native multi-tenant pattern (same as Istio gateways, ArgoCD). No RBAC layer, no cross-namespace routing, no multi-tenancy isolation to build.
2. **Security isolation** -- each team's gateway only accesses its own namespace's queues and actors. No shared failure domain, no cross-tenant data leakage risk.
3. **Throughput guarantees** -- teams independently size their gateways. High-traffic teams get dedicated resources; low-traffic teams run minimal instances. No noisy-neighbor problem.
4. **Queue naming already namespace-aware** -- `asya-{namespace}-{actor}` means the gateway doesn't need namespace routing logic. It just works within its own namespace.
5. **Too early for centralization** -- no production multi-team usage data to justify the complexity. Central gateway can be revisited when operational overhead of per-namespace deployments becomes measurable.

**Revisit triggers**:
- SRE needs a single dashboard across all namespaces
- Cross-team tool discovery becomes a requirement
- Per-namespace gateway count exceeds operational capacity

**See also**: `1frksi` (duplicate research task, also closed)


---
_Migrated from beads `asya-55z`_
