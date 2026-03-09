---
title: Support namespace-scoped flavors via ConfigMaps
priority: 3 # low
dependencies:
  - u5pd
---

## Summary

Currently, flavors are backed by Crossplane EnvironmentConfigs which are cluster-scoped only. DS teams cannot create their own flavors in their namespace without cluster admin access.

## Goal

Allow namespace-scoped flavors by reading from ConfigMaps (labeled asya.sh/flavor=<name>) in the actor's claim namespace, in addition to cluster-scoped EnvironmentConfigs.

## Design

Extend `function-asya-flavors` to:
1. Get claim namespace from XR label crossplane.io/claim-namespace
2. For each flavor name, look up a ConfigMap by label in the claim namespace via direct Kubernetes API call
3. Fall back to cluster-scoped EnvironmentConfig if not found in namespace
4. Same merge semantics as cluster-scoped flavors

### Requirements
- Kubernetes client setup in the function (~20 lines)
- ConfigMap lookup by label in claim namespace (~60-80 lines)
- RBAC: ClusterRole granting list ConfigMaps across namespaces (~15 lines YAML)
- Fallback ordering: namespace ConfigMap > cluster EnvironmentConfig

### Estimated delta
~150 lines of Go + ~15 lines of YAML. Clean additive change, no breaking changes to existing flavor behavior.

## Depends on
- u5pd (fix composition asymmetry / simplify flavor function first)
