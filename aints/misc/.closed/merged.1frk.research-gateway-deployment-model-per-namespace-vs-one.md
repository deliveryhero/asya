---
title: "Research: Gateway deployment model — per-namespace vs one-per-cluster"
priority: 4 # backlog
tags:
  - type:feature
reason: "Decided: per-namespace gateway for simplicity, security isolation, and throughput guarantees. ADR added to 1fc44c."
---





Investigate pros and cons of generalizing asya-gateway from per-user-namespace deployment to a single cluster-wide instance in asya-system.

Current model: Gateway is deployed per business namespace (e.g., default, production) alongside actors and crew. Each namespace gets its own gateway instance.

Proposed alternative: Single gateway in asya-system serving all namespaces. Would require:
- Namespace-aware routing (gateway must route messages to correct namespace queues)
- RBAC/multi-tenancy separation (prevent cross-namespace access)
- Namespace parameter in MCP tool calls or automatic detection
- Cross-namespace service discovery for actor queues

Research areas:
1. Multi-tenancy implications — how to isolate namespaces at the gateway level
2. RBAC model — what authorization is needed for cross-namespace operations
3. Operational trade-offs — single point of failure vs simpler management
4. Database isolation — shared PostgreSQL vs per-namespace databases
5. Performance — single gateway handling all traffic vs distributed
6. Migration path — how to transition from per-namespace to cluster-wide

Context: This came up during the asya-operator removal (PR #160) when reviewing namespace placement of components. The release-drafter template was incorrectly placing gateway in asya-system.


---
_Migrated from beads `asya-ccqy`_
