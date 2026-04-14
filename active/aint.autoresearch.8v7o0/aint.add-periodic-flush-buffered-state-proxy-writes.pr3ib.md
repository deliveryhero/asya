---
title: Add periodic flush to buffered state proxy writes
status: open
priority: 2 # medium
tags: [autoresearch, state-proxy, runtime]
dependencies: [8v7o0/jbtnm]
---

## Context

`_BufferedWriteFile` in asya_runtime.py buffers all writes in a
`SpooledTemporaryFile` and only PUTs to S3 on `close()`. If the actor pod
crashes before close, all buffered data is lost.

This affects TFEvents (TensorBoard), JSONL metrics logs, and any long-running
writes. The append mode aint (jbtnm) makes this more critical since append
workloads tend to be long-lived.

## Scope

Add a configurable periodic flush to `_BufferedWriteFile`:

1. Background thread/timer that PUTs current buffer to S3 every N seconds
   (configurable via `ASYA_FLUSH_INTERVAL`, default 30s)
2. On flush: PUT current buffer contents, do NOT clear buffer (next flush
   sends the full file again — correct for S3 which is whole-object PUT)
3. On close: final PUT + cancel timer
4. `flush()` method triggers immediate PUT (for explicit fsync semantics)

## Testing

- Unit: verify periodic flush triggers PUT at interval
- Unit: verify crash recovery — data written before last flush is persisted
- Unit: verify close cancels timer cleanly
