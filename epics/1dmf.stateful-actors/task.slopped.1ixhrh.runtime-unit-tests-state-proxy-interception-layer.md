---
title: "Runtime: Unit tests for state proxy interception layer"
priority: 2 # medium
type: task
---

Unit tests for the state proxy interception in asya_runtime.py:

Test categories:
1. Mount parser tests
   - Single mount, multiple mounts
   - Valid/invalid formats
   - Option parsing (write=buffered, write=passthrough)

2. Path resolution tests
   - Mount matching and key extraction
   - Non-state paths fall through
   - os.fspath normalization (str, bytes, PathLike)

3. File I/O wrapper tests (with mock HTTP server on Unix socket)
   - _StateFile: buffered read (seekable), passthrough read (not seekable), text mode
   - _BufferedWriteFile: write + close sends PUT, context manager
   - _PassthroughWriteFile: chunked writes, close finalizes

4. Error mapping tests
   - HTTP 404 -> FileNotFoundError
   - HTTP 409 -> FileExistsError
   - All status codes in mapping table

5. Patching tests
   - builtins.open intercepted for state paths
   - os.stat, os.listdir, os.scandir, os.unlink patched
   - os.makedirs is no-op for state paths
   - Non-state paths use original functions

6. Local dev parity
   - When ASYA_STATE_PROXY_MOUNTS is unset, no patching occurs

Phase: 2 (Runtime interception)
