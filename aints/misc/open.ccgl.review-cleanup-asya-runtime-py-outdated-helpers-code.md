---
title: "Review + cleanup asya_runtime.py: outdated helpers, code duplication, missing corner-case tests"
priority: 2 # medium
---

## Context

`src/asya-runtime/asya_runtime.py` is the single-file runtime — no external deps, must stay lean and correct.
During review, several issues were identified across three categories.

---

## Issues Found

### 1. Outdated / questionable public API — `fly_text` and `fly_status` (lines 126–148)

These module-level helpers build A2A-specific FLY payload dicts.

**Problems:**
- They use Python 2.7-era type comments (`# type: (str, str, bool) -> dict`) instead of modern type annotations — inconsistent with the rest of the file.
- `fly_status` hardcodes `state: "WORKING"` — may be stale vs. current A2A state machine.
- It is unclear whether these are still part of the public handler API contract or internal helpers. If public, they need proper docs and stable shape. If internal/dead, they should be removed.

**Action:** Audit against A2A spec. Either modernize signatures + add to ABI reference, or remove and update any examples/docs that reference them.

---

### 2. Code duplication — `_drive_generator` vs `_drive_async_generator` (lines 546–639)

The two functions are nearly identical — only the iteration primitives differ (`gen.send()` / `StopIteration` vs `gen.asend()` / `StopAsyncIteration`). The verb-dispatch block (FLY, GET, SET, DEL, emit frame) is copy-pasted.

**Action:** Extract the shared dispatch logic into a helper, or accept the duplication with a comment explaining why it cannot be unified.

---

### 3. Python version claim in module docstring (line 4)

The docstring says `Supported Python versions: 3.7+`, but the code uses:
- `dict[str, Any]` return annotations — requires 3.9+
- `Exception | None` union syntax — requires 3.10+

**Action:** Update the docstring to reflect actual minimum version (`3.10+` or `3.12+`).

---

### 4. `.status` writable path not in docs/spec

`_check_set_access` (line 534) allows writing to `.status` via `yield "SET", ".status", ...`, but `AGENTS.md` only lists `.route.next` and `.headers` as writable. The ABI reference doc (`docs/reference/abi-protocol.md`) should also be checked.

**Action:** Either document `.status` as a writable path (with semantics), or remove it from `_check_set_access`/`_check_del_access` if it was added accidentally.

---

### 5. Missing corner-case tests

Current test suite (`test_asya_runtime.py`, ~3300 lines) has excellent coverage overall, but misses:

- **FLY in non-SSE (batch) mode**: `_drive_generator` silently drops FLY events when `on_fly=None`. No warning is emitted. Should this warn? Test should assert the current behavior explicitly.
- **DEL verb in async generator** (`_drive_async_generator`): `TestAsyncGeneratorHandlers` has no DEL test.
- **Unknown verb in async generator**: `test_protocol_error_unknown_verb` only tests sync generator.
- **`_build_frame` with mid-stream route modification**: when a generator does multiple yields and modifies `.route.next` between emits, each frame should use the snapshot at emit time — not tested explicitly.
- **`fly_text` with `last=True` flag**: `test_fly_text_custom_artifact_id` covers it, but there is no test verifying `last=False` is the default.

**Action:** Add targeted tests for each gap above.

---

## Out of scope

- `_InvokeHandler.do_POST` re-parses the envelope instead of reusing `_handle_invoke` — intentional for SSE streaming, acceptable as-is.
- State proxy (`_install_state_proxy_hooks`, etc.) — separate concern, covered by `test_state_proxy.py`.
