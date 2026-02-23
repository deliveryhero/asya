---
title: Test CAS conflict handling (connector-level and asya-level retries)
priority: 2 # medium
type: task
---

Test the two-layer retry strategy for CAS conflicts:

Layer 1: Connector-internal retries
- Simulate concurrent writes to same key from multiple actors
- Verify connector retries on CAS conflict (redis WATCH/EXEC failure)
- Verify configurable CAS_MAX_RETRIES and CAS_RETRY_DELAY_MS
- Verify connector returns 409 after exhausting retries

Layer 2: Asya-level message requeue
- When connector returns 409, runtime raises FileExistsError
- Sidecar nacks message, it returns to queue
- On retry, handler re-runs fresh with new read() seeing latest value
- Verify eventual convergence under sustained contention

Test setup: Docker Compose with redis-buffered-cas connector + Redis + multiple concurrent writers.

Phase: 5 (Testing and documentation)
