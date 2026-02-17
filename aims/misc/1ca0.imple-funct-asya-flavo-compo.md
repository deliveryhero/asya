---
title: Implement function-asya-flavors Composition Function
status: open
priority: 2 # medium
type: task
---

Create a Crossplane Composition Function that fetches flavor EnvironmentConfigs individually and applies strategic merge patch to resolve a unified AsyncActor spec.

RFC: docs/rfc/actor-flavors/rfc-actor-flavors.md (Section 4.2, 4.4, ADR-4)

Overview:
function-asya-flavors is a Go Composition Function using function-sdk-go. It reads spec.flavors from the XR, fetches each EnvironmentConfig individually by label (asya.sh/flavor: <name>) via function-extra-resources, applies strategic merge patch in order, then applies actor inline spec as final override.

Key design decision: The function fetches EnvironmentConfigs individually (not via Crossplane's built-in EnvironmentConfig merge) because Crossplane's merge clobbers arrays. Individual fetch preserves each flavor's data intact for correct strategic merge.

EnvironmentConfig data format:
Each EnvironmentConfig's data field is a partial AsyncActor spec — same schema, same nesting. No wrapper keys:
  data:
    scaling:
      minReplicas: 1
    workload:
      template:
        spec:
          containers:
          - name: asya-runtime
            env:
            - name: FOO
              value: bar

Implementation:
- Scaffold: crossplane beta xpkg init function-asya-flavors function-template-go
- Source: src/function-asya-flavors/
- Dependencies: function-sdk-go, k8s.io/apimachinery/pkg/util/strategicpatch

RunFunction logic:
1. Read spec.flavors list from observed composite resource (XR)
2. For each flavor name, request extra resources: EnvironmentConfig with label asya.sh/flavor=<name>
3. For each flavor in spec.flavors order, extract its data (partial AsyncActor spec)
4. Apply strategic merge patch: env by 'name', tolerations by 'key', containers by 'name'
5. Apply actor's inline workload.template spec as final override (always wins)
6. Write fully resolved spec to a well-known context key (e.g., asya.sh/resolved-spec)

Build and deploy:
- Dockerfile in src/function-asya-flavors/
- OCI image: ghcr.io/<org>/function-asya-flavors:<version>
- Install via Function CR in Helm chart
- Add Makefile targets for build, test, lint

Testing:
- Unit tests for strategic merge logic (env var merge by name, toleration merge by key, resource override)
- Unit tests for missing flavor handling (flavor in spec.flavors but no matching EnvironmentConfig)
- Unit tests for empty flavors list (passthrough, no changes)
- Test with valueFrom/secretKeyRef env vars
- Test that actor inline spec always wins over flavor values


---
**Close reason**: Implemented in PR #177. Function resolves flavor EnvironmentConfigs via strategic merge patch using K8s PodSpec annotations. 17 unit tests covering merge logic, RunFunction flow, edge cases.


---
_Migrated from beads `asya-v2pa`_
