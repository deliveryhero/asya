---
title: "Phase 2.4: Add readiness check (reject if infrastructure not ready)"
priority: 1 # high
dependencies:
  - 1cph/1f4o91
---




Implement readiness check to prevent pod creation before infrastructure is ready.

## Tasks

1. Check AsyncActor.status.conditions for Ready=True
2. If AsyncActor not Ready:
   - Reject pod creation with retryable error
   - Include helpful message: 'AsyncActor infrastructure not ready, will retry'
3. If AsyncActor not found:
   - Reject with non-retryable error: 'AsyncActor X not found in namespace Y'
4. Test rejection behavior with unready AsyncActor
5. Verify Kubernetes retries pod creation after rejection

## Acceptance Criteria

- Pod creation rejected when AsyncActor not Ready
- Pod creation succeeds when AsyncActor is Ready
- Error messages are clear and actionable
- Kubernetes automatically retries after transient rejection

## Technical Notes

- Use admission.Denied() with appropriate status code
- 503 for 'not ready yet' (transient, will be retried)
- 400 for 'not found' (non-transient)
- This prevents race conditions where pods start before queue exists

## Reference

See docs/rfc/rfc-crossplane.md Section 6 (Injection Flow step 4)


---
**Close reason**: Closed


---
_Migrated from beads `asya-euj`_
