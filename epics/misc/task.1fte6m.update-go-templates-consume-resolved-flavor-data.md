---
title: Update Go templates to consume resolved flavor data
status: open
priority: 2 # medium
type: task
dependencies:
  - misc/1f76vf
  - misc/1fijg5
---




Update the existing function-go-templating templates in the Composition to read flavor-resolved spec from the context set by function-asya-flavors.

RFC: docs/rfc/actor-flavors/rfc-actor-flavors.md (Section 4.1)

Changes:
- File: deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml (Go template section)
- Update templates to read resolved spec from context key (asya.sh/resolved-spec) set by function-asya-flavors
- The resolved spec contains the fully merged workload template, scaling config, etc.
- Template should fall back to XR spec if no resolved spec exists (backward compatibility for actors without flavors)

Specific template changes:
- Deployment rendering: use resolved workload.template instead of raw XR spec
- ScaledObject rendering: use resolved scaling config
- Queue rendering: use resolved queue config (if any)
- ServiceAccount: unchanged (not flavor-affected initially)

Testing:
- Deploy an actor WITHOUT flavors — verify it renders identically to current behavior
- Deploy an actor WITH flavors — verify resolved values appear in rendered Deployment
- Verify env vars from flavors appear in the rendered container spec
- Verify actor inline overrides win over flavor values


---
_Migrated from beads `asya-aeko`_
