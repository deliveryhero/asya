---
title: Implement redis-buffered-cas connector
priority: 1 # high
type: task
---


Second connector: Redis with buffered writes and CAS (compare-and-swap) semantics.

- Implements all 6 StateProxyConnector methods against Redis
- read(): Redis GET, stores version/revision internally for subsequent CAS write
- write(): Redis SET with WATCH/MULTI/EXEC for CAS. On conflict, internal retry loop
- exists(): Redis EXISTS
- stat(): Redis STRLEN/TYPE
- list(): Redis SCAN MATCH with key-part parsing for prefix/delimiter semantics
- delete(): Redis DEL
- CAS configuration via env vars: CAS_MAX_RETRIES, CAS_RETRY_DELAY_MS
- Backend config via: STATE_ENDPOINT
- Unit tests including CAS conflict simulation

Demonstrates the two-layer retry strategy: connector-internal CAS retries (Layer 1).

Phase: 1 (Connector interface and framework)
