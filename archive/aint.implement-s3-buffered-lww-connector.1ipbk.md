---
title: Implement s3-buffered-lww connector
status: merged
priority: 1
parent: g5bkc
tags:
  - pr:195
---

First concrete connector: S3 with buffered writes and last-write-wins semantics.

- Implements all 6 StateProxyConnector methods against S3
- read(): S3 GetObject, returns full body with Content-Length (buffered)
- write(): S3 PutObject with full body (atomic, last-write-wins)
- exists(): S3 HeadObject
- stat(): S3 HeadObject, returns KeyMeta with size
- list(): S3 ListObjectsV2 with prefix/delimiter
- delete(): S3 DeleteObject
- Uses connector base framework for HTTP server
- Configurable via env vars: STATE_BUCKET, STATE_PREFIX, AWS_REGION
- Unit tests

Simplest connector (no CAS), serving as the reference implementation.

Phase: 1 (Connector interface and framework)
