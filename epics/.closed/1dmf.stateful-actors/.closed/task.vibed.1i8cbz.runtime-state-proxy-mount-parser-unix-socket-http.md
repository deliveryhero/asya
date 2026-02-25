---
title: "Runtime: State proxy mount parser, Unix socket HTTP client, error mapping"
priority: 1 # high
type: task
tags:
  - pr:195
dependencies:
  - 1dmf/1ipgpc
---


Add foundational state proxy infrastructure to asya_runtime.py:

1. ASYA_STATE_PROXY_MOUNTS env var parser
   - Format: {name}:{path}:{options}[;{name}:{path}:{options}]*
   - Example: meta:/state/meta:write=buffered;media:/state/media:write=passthrough
   - Split on ; for mounts, : for fields, , for options, = for key/val

2. Unix socket HTTP client (_UnixHTTPConnection)
   - Extends http.client.HTTPConnection
   - Connects via socket.AF_UNIX to /var/run/asya/state/{name}.sock
   - ~10 lines, zero dependencies

3. HTTP status to Python exception mapping (_raise_for_status)
   - 404 -> FileNotFoundError
   - 409 -> FileExistsError
   - 400 -> ValueError
   - 403 -> PermissionError
   - 413 -> OSError (EFBIG)
   - 500 -> OSError
   - 503 -> ConnectionError
   - 504 -> TimeoutError
   - ~15 lines

All must use zero external dependencies (stdlib only). asya_runtime.py remains a single file.

Phase: 2 (Runtime interception)
