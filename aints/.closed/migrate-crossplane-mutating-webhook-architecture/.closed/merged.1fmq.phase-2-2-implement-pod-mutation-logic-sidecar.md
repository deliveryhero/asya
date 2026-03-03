---
title: "Phase 2.2: Implement pod mutation logic (sidecar injection)"
priority: 1 # high
dependencies:
  - 1fm7
---




Implement the core sidecar injection logic that mutates pods.

## Tasks

1. Create MutatingWebhookConfiguration resource
2. Implement admission handler that:
   - Checks for asya.sh/inject=true label
   - Reads asya.sh/actor label to identify actor
   - Modifies pod spec to add sidecar container
3. Extract injection logic from current operator (src/asya-operator/internal/controller/inject.go)
4. Inject:
   - asya-sidecar container with probes
   - Socket volume (emptyDir) for runtime communication
   - Runtime ConfigMap volume mount
   - Tmp volume for runtime
5. Add environment variables to sidecar container
6. Unit test injection logic

## Acceptance Criteria

- Pod with asya.sh/inject=true gets sidecar injected
- Sidecar has correct probes (startup, liveness, readiness)
- Volumes correctly mounted
- Environment variables set

## Technical Notes

- Reuse injection logic from current operator where possible
- Sidecar config is hardcoded initially (will query AsyncActor later)
- Focus on correctness first, then configuration

## Reference

See docs/rfc/rfc-crossplane.md Section 6 (Injected Resources)


---
**Close reason**: Closed


---
_Migrated from beads `asya-1d8`_
