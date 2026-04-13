---
title: "Runtime: open(path, x) exclusive create mode for state proxy"
status: merged
priority: 2
parent: 4e5zh
tags:
  - pr:206
---

## Summary

Add support for Python's exclusive create mode (`"x"`, `"xb"`, `"xt"`) in `asya_runtime.py`'s file I/O interception layer. This is required by the aggregator's exactly-once emission sentinel pattern.

## Behavior

| Python mode | Behavior | State proxy mapping |
|-------------|----------|---------------------|
| `"x"`, `"xb"` | Create file, fail if exists | `PUT /keys/{key}` with `If-None-Match: *` header |
| `"xt"` | Same as `"x"` but text mode | Same, with text encoding |

## How It Works

- Python's `open(path, "x")` creates a file exclusively -- raises `FileExistsError` if it exists
- The state proxy connector receives `PUT /keys/{key}` with `If-None-Match: *`
- If key does not exist: create and return 200/204
- If key exists: return 412 Precondition Failed
- Runtime translates 412 -> `FileExistsError`, matching Python's native behavior

## Changes

### `src/asya-runtime/asya_runtime.py`
- In the mode-switching logic within `_open_write()` (or equivalent):
  - Detect `"x"`, `"xb"`, `"xt"` modes
  - Add `If-None-Match: *` header to the PUT request
  - Map 412 response to `FileExistsError`
- Small addition (~5 lines)

### Tests
- `open(path, "x")` succeeds when file does not exist
- `open(path, "x")` raises `FileExistsError` when file exists
- `open(path, "xb")` works in binary mode
- `open(path, "xt")` works in text mode
- Write content via exclusive create, verify it's readable
- Second exclusive create on same path raises `FileExistsError`

## References
- RFC: `.aint/epics/1c7i.stateful-fan-fan-out/rfc.md` (ADR-4, Runtime Enhancement section)
- Python docs: https://docs.python.org/3/library/functions.html#open (mode "x")
