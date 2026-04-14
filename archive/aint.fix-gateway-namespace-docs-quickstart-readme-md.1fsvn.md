---
title: Fix gateway namespace in docs/quickstart/README.md
status: merged
priority: 1
tags:
  - type:bug
---

## Problem

Current quickstart README incorrectly installs asya-gateway in the `asya-system` namespace (lines 425-453). This is architecturally wrong because:

1. **Gateway is business logic, not infrastructure**
   - Gateway exposes MCP tools for AsyncActors
   - Gateway routes messages to actor queues
   - Gateway should live in the same namespace as the actors it serves

2. **Namespace separation principle**
   - `asya-system`: Infrastructure (operator, monitoring)
   - Business namespaces (e.g., `default`, `production`): Gateway + AsyncActors + PostgreSQL

3. **Multi-tenancy implications**
   - Different teams may deploy actors in different namespaces
   - Each namespace should have its own gateway instance
   - Operator in asya-system serves all namespaces

## Current Incorrect Behavior

```bash
# Step 3: Install Gateway (WRONG - installs to asya-system)
helm install asya-gateway asya/asya-gateway \
  -n asya-system \
  -f gateway-values.yaml
```

## Expected Correct Behavior

```bash
# Step 3: Install Gateway (CORRECT - installs to business namespace)
helm install asya-gateway asya/asya-gateway \
  -n default \
  -f gateway-values.yaml
```

## Files to Update

### 1. docs/quickstart/README.md

**Section: "Add Gateway (Optional)"**

Update lines 373-453 to change namespace from asya-system to default for:
- PostgreSQL Service and Deployment
- PostgreSQL Secret
- Gateway Helm install
- Gateway database host configuration

**Section: "4. Update Operator for Gateway Integration"**

Update gatewayURL from:
- `http://asya-gateway.asya-system.svc.cluster.local:8080`
to:
- `http://asya-gateway.default.svc.cluster.local:8080`

**Section: "5. Update Crew for Gateway Reporting"**

Update ASYA_GATEWAY_URL environment variable to use default namespace.

**Section: "8. Test Gateway Integration"**

Update port-forward command from `-n asya-system` to `-n default`.

**Section: "Clean Up"**

Update gateway uninstall and resource deletion to use default namespace.

### 2. Add Architectural Clarification

Add a new section explaining namespace separation:

- asya-system: Infrastructure (operator, monitoring, transport services)
- Business namespaces: Gateway, AsyncActors, crew actors, PostgreSQL

Explain that gateway is business logic layer, not infrastructure.

## Testing

After changes, verify quickstart still works:

1. Follow updated README from scratch on Kind cluster
2. Verify gateway deploys to `default` namespace
3. Verify gateway can reach actors and LocalStack
4. Test MCP call works
5. Verify SSE streaming works

## Acceptance Criteria

- [ ] All gateway-related commands use `default` namespace (not `asya-system`)
- [ ] PostgreSQL deploys to `default` namespace
- [ ] Gateway service URLs updated to `.default.svc.cluster.local`
- [ ] Operator gateway URL points to default namespace
- [ ] Crew gateway URL points to default namespace
- [ ] Port-forward command uses correct namespace
- [ ] Cleanup section uses correct namespace
- [ ] New "Namespace Architecture" section added explaining separation
- [ ] Quickstart tested end-to-end on Kind cluster
- [ ] All kubectl/helm commands use correct namespace flags

## References

- Current quickstart: docs/quickstart/README.md
- Related issue: asya-u8y (bundle chart with correct namespace strategy)


**Close reason**: Fixed gateway namespace in quickstart. Created PR #120.


_Migrated from beads `asya-3dn`_
