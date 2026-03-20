---
title: "fix(state-proxy): implement exclusive create (xb mode) in server and CAS connectors"
priority: 1 # high
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/.worktrees/debt/rruz.fix-state-proxy-implement-exclusive-create-xb-mode
  - branch:debt/rruz.fix-state-proxy-implement-exclusive-create-xb-mode
  - pr:326
---



## Problem

The fan-in aggregator (src/asya-crew/asya_crew/fanin/split_key.py) uses open(path, "xb") for
exactly-once sentinel creation. The runtime correctly sends If-None-Match: * header on PUT, but
the real state proxy server ignores this header — the do_PUT handler passes data directly to
connector.write() with no exclusive create semantics.

The mock server in runtime tests (test_state_proxy.py:186-190) correctly handles If-None-Match: *,
masking the bug in the real server.

## Broken chain

```
Runtime: open("path", "xb") -> _BufferedWriteFile(exclusive=True) -> PUT with If-None-Match: *
Server:  do_PUT() -> connector.write(key, data, size)  <- header IGNORED
Connector: unconditional write (no exclusive semantics)
```

## Fix required across 3 layers

1. **interface.py**: Add exclusive: bool = False param to write()
2. **server.py:180**: Parse If-None-Match: * header, pass exclusive=True to connector
3. **CAS connectors** — use native atomic primitives:
   - S3: put_object(IfNoneMatch='*') (added Aug 2024)
   - GCS: upload_from_string(if_generation_match=0) (generation 0 = must not exist)
   - Redis: SET key value NX (atomic set-if-not-exists)
4. **LWW/Passthrough connectors**: accept param, do best-effort exists() check
5. **Tests**: exclusive create tests for each CAS connector + server integration test
