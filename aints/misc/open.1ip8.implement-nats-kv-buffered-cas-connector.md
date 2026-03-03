---
title: Implement nats-kv-buffered-cas connector
priority: 2 # medium
dependencies:
  - 1iph
---

NATS KV connector with buffered writes and revision-based CAS.

- read(): NATS KV Get, stores revision number for subsequent conditional write
- write(): NATS KV Update with expected revision. On conflict, retry loop
- exists(): NATS KV Get (key existence check)
- stat(): NATS KV Get (returns value size as KeyMeta)
- list(): NATS KV Keys with prefix filtering and delimiter-based grouping
- delete(): NATS KV Delete

NATS KV provides native revision-based CAS (every value has a monotonic revision).
Uses nats-py client library.

CAS flow uses NATS KV's built-in revision tracking:
1. Get(key) returns value + revision
2. Update(key, value, last=revision) is conditional write
3. On KeyWrongLastSequenceError: re-get, retry

Configurable via: STATE_NATS_URL, STATE_KV_BUCKET, CAS_MAX_RETRIES, CAS_RETRY_DELAY_MS

Phase: 4 (Additional connectors)
