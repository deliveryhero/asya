---
title: "Runtime: Read/write file wrappers (_StateFile, _BufferedWriteFile, _PassthroughWriteFile)"
priority: 1 # high
type: task
dependencies:
  - 1dmf/1ipgpc
---

Implement the file-like wrapper classes in asya_runtime.py:

1. _StateFile (read wrapper)
   - Auto-detects buffered vs passthrough from HTTP response:
     - Content-Length present -> buffer into SpooledTemporaryFile (seekable)
     - Chunked transfer -> wrap response directly (not seekable)
   - Supports text mode (encoding/decoding) and binary mode
   - Context manager (__enter__/__exit__)
   - f.seek(), f.tell() work for buffered; raise UnsupportedOperation for passthrough

2. _BufferedWriteFile
   - Buffers writes in SpooledTemporaryFile (4MB in-memory, then disk spill)
   - On close(): sends full body as PUT /keys/{key} with Content-Length
   - Context manager support
   - Seekable (writes are local until close)

3. _PassthroughWriteFile
   - Opens chunked PUT /keys/{key} immediately
   - Each write() sends a chunk to the proxy
   - close() finalizes chunked transfer (sends 0\r\n\r\n)
   - Not seekable

All wrappers use _UnixHTTPConnection and _raise_for_status from the core infrastructure task.

Phase: 2 (Runtime interception)
