---
title: Adopt ABI yield protocol instead of VFS for actor-runtime communication
status: merged
priority: 2
children:
  - 1pjor
---

## Context

Actors currently interact with message metadata (route, headers, status) through
a virtual filesystem (VFS) at `/proc/asya/msg/`. This requires OS-level file I/O,
FUSE-like mount points, and makes testing require filesystem mocking.

## Decision

Replace VFS with a **yield-based ABI** where generator actors communicate with
the runtime via typed `yield` instructions:

```python
# VFS (current)
with open("/proc/asya/msg/route/next", "w") as f:
    f.write(json.dumps(["a", "b"]))

# ABI (new)
yield "SET", ".route.next", ["a", "b"]
```

Four verbs: **GET**, **SET**, **DEL** (structural JSON operations) and **FLY**
(upstream streaming events, replacing the `partial: True` convention).

Path syntax: jq-like dot access (`.route.next`) with Python-like list slicing
(`[0]`, `[:0]`, `[-1]`, `[3:5]`).

## Key Properties

- **Pure Python**: no file I/O, no OS dependencies, trivially testable
- **Type-dispatched**: runtime dispatches on `type(yielded_value)` — tuples are
  ABI instructions, bare dicts are downstream payloads
- **No payload inspection**: runtime never looks inside dict payloads for control
  signals (unlike `partial: True` which mixed control and data)
- **Composable**: `yield from` (sync) or explicit iteration (async) for delegation

## Scope

- Define ABI spec (abi-protocol.md — draft exists)
- Implement ABI dispatch in `asya_runtime.py` (replaces VFS handling)
- Implement path resolver (jq-like dot + Python slicing)
- Update compiler codegen to emit ABI yields instead of VFS writes
- Remove VFS mount from injector/sidecar
- Update all tests

## Supersedes

- Epic 1ixt (message metadata VFS)
