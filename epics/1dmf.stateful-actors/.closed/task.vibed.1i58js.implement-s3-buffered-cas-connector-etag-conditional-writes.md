---
title: Implement s3-buffered-cas connector (ETag conditional writes)
priority: 2 # medium
type: task
tags:
  - pr:200
dependencies:
  - 1dmf/1iph0b
---




S3 connector with buffered writes and CAS via ETag/If-Match conditional PutObject.

- read(): S3 GetObject, stores ETag for subsequent conditional write
- write(): S3 PutObject with If-Match header using stored ETag
  - On 412 PreconditionFailed: re-read latest ETag, retry up to CAS_MAX_RETRIES
  - On exhausted retries: return HTTP 409 (runtime raises FileExistsError)
- exists()/stat()/list()/delete(): same as s3-buffered-lww

CAS flow:
1. Handler reads -> connector stores ETag
2. Handler writes -> connector sends PutObject with If-Match: {stored-etag}
3. Conflict (another writer changed object) -> connector re-reads, retries
4. Persistent conflict -> 409 -> runtime raises -> sidecar requeues (Layer 2)

Configurable via: STATE_BUCKET, STATE_PREFIX, AWS_REGION, CAS_MAX_RETRIES, CAS_RETRY_DELAY_MS

Phase: 4 (Additional connectors)
