---
title: "Fix injector: wrong SQS region env var + missing SQS endpoint"
status: done
priority: 1 # high
type: task
tags:
  - type:bug
---



Two bugs in asya-injector (crossplane-phase2 worktree) discovered during Phase 3.5 lifecycle testing:

## Bug 3: Wrong env var name for SQS region

**File**: .worktrees/crossplane-phase2/src/asya-injector/internal/injection/inject.go (line 118)
**Problem**: Injector sets ASYA_SQS_REGION but sidecar reads ASYA_AWS_REGION (src/asya-sidecar/internal/config/config.go:74). Region is always default us-east-1.
**Fix**: Change line 118 from ASYA_SQS_REGION to ASYA_AWS_REGION. Update inject_test.go accordingly.

## Bug 4: Missing ASYA_SQS_ENDPOINT for LocalStack

**Files**:
- .worktrees/crossplane-phase2/src/asya-injector/internal/config/config.go
- .worktrees/crossplane-phase2/src/asya-injector/internal/injection/inject.go
- .worktrees/crossplane-phase2/deploy/helm-charts/asya-injector/values.yaml
- .worktrees/crossplane-phase2/deploy/helm-charts/asya-injector/templates/deployment.yaml

**Problem**: Sidecar needs ASYA_SQS_ENDPOINT (mapped to SQSBaseURL in sidecar config) to connect to LocalStack. Without it, SQS SDK tries real AWS endpoints. Injector has no config field for this.
**Fix**:
1. Add SQSEndpoint string field to config.go, loaded from ASYA_SQS_ENDPOINT env var
2. In inject.go SQS transport block, add ASYA_SQS_ENDPOINT env var to sidecar container if configured
3. Add sqsEndpoint to values.yaml config section
4. Add ASYA_SQS_ENDPOINT env var to deployment.yaml template

These fixes should be applied in the crossplane-phase2 worktree and submitted as a PR.


---
**Close reason**: Fixed: Renamed ASYA_SQS_REGION to ASYA_AWS_REGION. Added SQSEndpoint config field, ASYA_SQS_ENDPOINT env var injection, and Helm chart support.


---
_Migrated from beads `asya-6y8`_
