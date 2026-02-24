---
title: "Composition: Add function-asya-flavors to pipeline"
priority: 2 # medium
type: task
---





Add function-asya-flavors as the first step in the SQS (and future transport) Composition pipeline, before function-go-templating.

RFC: docs/rfc/actor-flavors/rfc-actor-flavors.md (Section 4.1)

Changes:
- File: deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml
- Add function-asya-flavors as pipeline step 1 (before existing go-templating step)
- No EnvironmentConfig selector slots needed (the function fetches individually)
- Add the Function CR template for function-asya-flavors in the Helm chart

Pipeline order:
1. function-asya-flavors (new) - resolves flavors, writes merged spec to context
2. function-go-templating (existing) - reads resolved spec, renders resources
3. function-auto-ready (existing) - marks composite ready

The function-asya-flavors step must run before go-templating so that the Go templates receive the fully resolved spec.

Testing:
- Verify existing actors without flavors still work (function passes through when spec.flavors is empty)
- Verify an actor with flavors gets the function invoked
- Helm template renders valid Composition with the new pipeline step


---
_Migrated from beads `asya-ej6i`_
