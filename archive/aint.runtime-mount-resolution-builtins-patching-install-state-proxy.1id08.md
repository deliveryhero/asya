---
title: "Runtime: Mount resolution and builtins patching (_install_state_proxy_hooks)"
status: merged
priority: 1
tags:
  - pr:195
---

Implement the function patching layer in asya_runtime.py:

_install_state_proxy_hooks(mounts_str) patches 6 Python functions:

1. builtins.open -> intercepts open() for state mount paths
   - Matches path against configured mount prefixes
   - Strips mount prefix to get key
   - Dispatches to _open_read() or _open_write() based on mode
   - Falls through to original open() for non-state paths

2. os.stat -> intercepts os.stat() and os.path.exists()
   - HEAD /keys/{key}, returns synthetic stat_result
   - st_size from Content-Length, st_mode fixed (S_IFREG|0644 or S_IFDIR|0755)
   - exists() returns False on 404 (not exception)

3. os.listdir -> intercepts os.listdir()
   - GET /keys/?prefix={p}&delimiter=/
   - Returns list of immediate children (files + dirs)

4. os.scandir -> intercepts os.scandir() / pathlib.Path.iterdir()
   - Same HTTP call as listdir, returns DirEntry-like objects

5. os.unlink -> intercepts os.remove() / os.unlink()
   - DELETE /keys/{key}

6. os.makedirs -> no-op for state paths (prefixes are virtual)

Path resolution: os.fspath() normalizes all path arguments. Mount matching checks if path starts with any configured mount prefix.

Activation: called at startup before handler loading, only when ASYA_STATE_PROXY_MOUNTS is set.

Phase: 2 (Runtime interception)
