---
title: "Phase 4.0: Update quickstart docs for Crossplane setup"
status: merged
priority: 2
dependencies:
  - 1fm4
---

Update the quickstart documentation to reflect the new Crossplane + Webhook architecture.

## Tasks

1. Update quickstart README with new installation steps:
   - Install Crossplane (Helm chart)
   - Install provider-aws and provider-kubernetes
   - Configure ProviderConfig for AWS
   - Install asya-injector webhook
   - Install asya-crossplane (XRDs + Compositions)
2. Update AsyncActor example manifests for new API
3. Document label requirements (asya.sh/inject, asya.sh/actor)
4. Add troubleshooting section for common issues:
   - Crossplane provider not ready
   - Webhook certificate issues
   - SQS queue creation failures
5. Test documentation accuracy by following it yourself

## Acceptance Criteria

- New user can follow quickstart and deploy an AsyncActor
- All commands in docs are tested and working
- Examples use new Crossplane-style AsyncActor API
- Troubleshooting covers common failure modes

## Technical Notes

- This should be done BEFORE E2E tests so manual validation catches issues first
- Focus on the happy path, edge cases go in detailed docs
- Keep it concise - link to detailed docs for deep dives

## Reference

See docs/rfc/rfc-crossplane.md Section 9


---
**Close reason**: Quickstart docs created and validated in README_CROSSPLANE.md, fixes applied in d2198ae


---
_Migrated from beads `asya-k3v`_
