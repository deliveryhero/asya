---
title: "Implement asya local: generate docker-compose from XRDs for local testing"
status: open
priority: 4 # backlog
type: task
---

Enable DS to test flows locally without Kubernetes by generating docker-compose.yml from AsyncActor XRD claims.

**Context:**
- DS want to test flows locally before deploying to K8s
- Kind/k3d/minikube require complex setup (KEDA, operators) and are platform-dependent
- Docker Compose is familiar to DS and starts in seconds

**Proposed solution:**
`asya local up flows/my-flow/` generates and runs docker-compose from compiled manifests.

**Implementation ideas:**
1. Parse AsyncActor claims from manifests/
2. Generate docker-compose.yml with:
   - RabbitMQ container (local transport)
   - Per-actor: runtime container + sidecar container
   - Shared Unix socket volumes
3. Ignore K8s-specific features (KEDA, node affinity, profiles)

**Simplification to explore:**
Instead of multiple sidecars, consider a central 'orchestrator' container that:
- Reads flow graph
- Calls actors sequentially via HTTP/socket
- Manages routing logic centrally
This would reduce docker-compose complexity significantly.

**Dependencies:**
- Crossplane XRD format must be stabilized first
- Depends on: asya-vab (Crossplane migration)

**Blocked by:** Crossplane implementation and XRD stabilization


---
_Migrated from beads `asya-u8x`_
