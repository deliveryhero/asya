---
title: Migrate credential env var mounting to asya-injector
status: merged
priority: 2
parent: h0mji
dependencies:
  - 1f1x
---

Update asya-injector to mount transport credential secrets into the sidecar container it injects.

## Context

The injector currently adds the sidecar container with hardcoded env vars but does NOT add secretKeyRef entries for transport credentials. The operator used to handle this in `buildSidecarEnv()`. With the credential Secret now created by Crossplane Composition (asya-kp6), the injector must reference it.

## Tasks

1. When transport is `sqs`, add env vars to sidecar container:
   - `AWS_ACCESS_KEY_ID` → secretKeyRef from `{actor-name}-transport-creds`, key `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY` → secretKeyRef from `{actor-name}-transport-creds`, key `AWS_SECRET_ACCESS_KEY`
2. Follow convention: secret name is always `{actor-name}-transport-creds`
3. Add unit tests for credential injection
4. Test end-to-end with LocalStack SQS

## Acceptance Criteria

- Sidecar container gets AWS credentials mounted via secretKeyRef
- Sidecar can authenticate to SQS queue using injected credentials
- No credentials are hardcoded or logged
- Unit tests cover SQS credential injection path

## Technical Notes

- Actor name comes from `asya.sh/actor` label (already read by injector)
- See operator's `buildSidecarEnv()` at `asya_controller.go:1060-1140` for reference
- Only SQS transport needed for now (RabbitMQ is out of scope for crossplane migration)
- Injector source: src/asya-injector/internal/injection/inject.go

## Reference

Injector codebase: .worktrees/crossplane-phase2/src/asya-injector/
Operator reference: src/asya-operator/internal/controller/asya_controller.go


---
**Close reason**: Already implemented: config.AWSCredsSecret → envFrom secretRef. Added unit tests (TestInjector_InjectAWSCredentials, TestInjector_InjectNoAWSCredentials). Validated credentials resolve in sidecar container in Kind cluster.


---
_Migrated from beads `asya-k7n`_
