---
title: Test passthrough streaming for large files
priority: 2 # medium
type: task
---

Test passthrough connectors with large file streaming:

Read path:
- Stream large file (>100MB) from S3 via passthrough connector
- Verify chunked transfer encoding (no Content-Length)
- Verify runtime wraps response as non-seekable stream
- Verify seek() raises io.UnsupportedOperation
- Verify chunk-by-chunk reading works correctly

Write path:
- Stream large file to S3 via passthrough connector
- Verify chunked PUT with multipart upload
- Verify data integrity (MD5/checksum comparison)
- Verify partial write on simulated crash leaves partial data (non-atomic)

Memory usage:
- Verify memory stays bounded during large file streaming
- Neither runtime nor connector should buffer the full file in memory

Test setup: Docker Compose with s3-passthrough connector + MinIO, large test files.

Phase: 5 (Testing and documentation)
