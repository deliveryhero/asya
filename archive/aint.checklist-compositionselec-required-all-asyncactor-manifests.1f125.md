---
title: "Checklist: compositionSelector required on all AsyncActor manifests"
status: merged
priority: 3
tags:
  - pr:197
reason: "PR #197 merged: compositionSelector now auto-injected by webhook from spec.transport — manual checklist superseded by injector automation"
---

When adding a new Crossplane Composition for a new transport, ALL AsyncActor manifests (Helm templates AND dynamic test manifests) MUST include compositionSelector.matchLabels to select the correct Composition. Without it, Crossplane picks non-deterministically when multiple Compositions exist for the same XRD.

Checklist for new transport additions:
1. Helm chart templates: deploy/helm-charts/asya-actor/, asya-crew/, testing/e2e/charts/asya-test-actors/, asya-test-flows/
2. Dynamic test manifests: testing/e2e/tests/test_crossplane_e2e.py, test_keda_scaling.py
3. The _actor_manifest() helper in test_crossplane_e2e.py
4. New composition must include function-auto-ready as final pipeline step

Pattern:
  spec:
    compositionSelector:
      matchLabels:
        asya.sh/transport: <transport-name>
    transport: <transport-name>

Learned from PR #161 (RabbitMQ Crossplane composition) where missing selectors caused flaky E2E failures.


---
_Migrated from beads `asya-yje0`_
