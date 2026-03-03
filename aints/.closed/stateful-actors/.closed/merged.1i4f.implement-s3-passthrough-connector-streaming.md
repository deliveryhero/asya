---
title: Implement s3-passthrough connector (streaming)
priority: 2 # medium
tags:
  - pr:200
dependencies:
  - 1dmf/1iph0b
---




Streaming S3 connector with passthrough writes (non-atomic, last-write-wins).

- read(): S3 GetObject, returns streaming body directly (chunked, no Content-Length)
- write(): S3 CreateMultipartUpload + UploadPart in 8MB chunks + CompleteMultipartUpload
- exists()/stat()/list()/delete(): same as s3-buffered-lww

Key difference from s3-buffered-lww:
- Reads are streamed (not buffered), runtime detects chunked encoding -> not seekable
- Writes use S3 multipart upload for streaming -> non-atomic (partial data on crash)
- Designed for large files: video, datasets, model weights

Configurable via: STATE_BUCKET, STATE_PREFIX, AWS_REGION, MULTIPART_CHUNK_SIZE_MB (default 8)

Phase: 4 (Additional connectors)
