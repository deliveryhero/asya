---
title: "Crossplane: Update compositions for stateProxy"
priority: 2 # medium
type: task
---



Update Crossplane compositions to propagate stateProxy configuration:

- Pass stateProxy array from AsyncActor claim through to the workload pod spec
- Ensure the injector receives the stateProxy annotation/label for processing
- Update composition pipeline to handle the new XRD field
- Validate stateProxy field is properly propagated in composition tests

The composition itself doesn't create state proxy resources (connectors are user-provided images). It only ensures the spec reaches the injector webhook.

Phase: 3 (Injector and XRD integration)
