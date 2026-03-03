---
title: Fix unprefixed labels in Helm charts to use asya.sh/ domain
priority: 2 # medium
tags:
  - type:bug
---





Several Helm charts use unprefixed labels (actor, actor-type, flow, test-type, hop-index) on AsyncActor CRs instead of domain-scoped asya.sh/ labels. The operator and Crossplane composition correctly use asya.sh/actor, but the crew chart and test charts are inconsistent.

Files to fix:
- deploy/helm-charts/asya-crew/templates/_helpers.tpl: actor → asya.sh/actor
- testing/e2e/charts/asya-test-flows/templates/_helpers.tpl: test-type → asya.sh/test-type
- testing/e2e/charts/asya-test-flows/templates/nested-if-handlers.yaml: flow → asya.sh/flow, actor-type → asya.sh/actor-type
- testing/e2e/charts/asya-test-flows/templates/nested-if-routers.yaml: flow → asya.sh/flow, actor-type → asya.sh/actor-type
- testing/e2e/charts/asya-test-actors/templates/actor-multihop.yaml: test-type → asya.sh/test-type, hop-index → asya.sh/hop-index


---
**Close reason**: Fixed all unprefixed labels in Helm charts (crew, test-flows, test-actors) and removed asya.sh/ from operator reserved prefix list


---
_Migrated from beads `asya-3ba`_
