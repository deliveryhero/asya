---
title: "Integration tests: retry flow with exponential backoff"
status: open
priority: 2 # medium
type: task
---

Add integration tests for the retry flow in testing/integration/ or testing/component/.

Test scenarios:
1. Handler fails once, succeeds on retry -> message reaches _sink with phase: succeeded
2. Handler fails max_attempts times -> message reaches _sink with phase: failed, reason: MaxRetriesExhausted
3. Handler throws fatal error (in nonRetryableErrors) -> immediate _sink with reason: NonRetryableFailure
4. Verify backoff delay increases exponentially (measure time between attempts)
5. Verify attempt counter resets when message moves to next actor
6. Verify status.created_at is preserved across retries
7. Verify status.error is cleared on successful retry
8. Verify complete message is persisted to S3 by _sink (redrivable)

Test infrastructure:
- Testing actors with configurable failure behavior (fail N times then succeed, always fail, throw specific error types)
- Docker Compose with SQS (LocalStack) transport
- Assertions on _sink messages in S3/MinIO

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md


---
_Migrated from beads `asya-i1vw`_
