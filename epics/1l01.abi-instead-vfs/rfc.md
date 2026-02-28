# RFC: Yield ABI for Actor-Runtime Communication

## 1. Summary

Replace the VFS-based metadata access (`_MessageVFS`, builtins patching,
`/proc/asya/msg/`) with a yield-based ABI protocol where generator actors
communicate with the runtime via typed `yield` instructions (GET/SET/DEL/FLY).

This removes ~370 lines of builtins monkey-patching and virtual filesystem
emulation from `asya_runtime.py`, replaces them with ~170 lines of path
resolver + dispatch engine, and simplifies compiler-generated router code
by eliminating file I/O boilerplate.

Full ABI specification: [abi-protocol.md](abi-protocol.md)

---

## 2. Motivation

### 2.1 VFS pain points

The current VFS intercepts `builtins.open`, `os.listdir`, `os.path.exists`,
`os.remove`, `os.makedirs`, and `os.rmdir` — six global function patches that
affect the entire Python process:

```python
# Runtime startup (asya_runtime.py:661-690)
builtins.open = _patched_open
io.open = _patched_open
os.listdir = _patched_listdir
os.path.exists = _patched_path_exists
os.path.isdir = _patched_path_isdir
os.remove = _patched_remove
os.makedirs = _patched_makedirs
os.rmdir = _patched_rmdir
```

This causes:
- **Testing complexity**: Tests must understand that `open()` is patched
- **Serialization overhead**: Lists stored as `\n`-separated strings, complex
  values as JSON strings, requiring encode/decode at handler level
- **Control/data mixing**: `partial: True` inside payload dicts forces the
  runtime to inspect every yielded dict for a magic key
- **Large surface area**: `_MessageVFS` (200 lines), `_MsgVirtualFile` (65
  lines), patching functions (90 lines) — 370 lines total for what is
  fundamentally dict access

### 2.2 What the ABI replaces it with

```python
# VFS: 4 lines of file I/O + string parsing
with open(f"{_MSG_ROOT}/route/next") as _f:
    _next_tail = _f.read().splitlines()
# ... later ...
with open(f"{_MSG_ROOT}/route/next", "w") as _f:
    _f.write("\n".join(_next + _next_tail))

# ABI: 2 lines of typed yields, native Python types
_next_tail = yield "GET", ".route.next"
# ... later ...
yield "SET", ".route.next", _next + _next_tail
```

No file I/O, no string serialization, no builtins patching.

---

## 3. Design Overview

### 3.1 Dispatch table

The runtime dispatches on Python type of the yielded value:

```
Yielded value                     Instruction     Runtime action
────────────────────────────────  ──────────────  ────────────────────────
{"key": "val"}                    EMIT            build frame, emit downstream
("FLY", {"token": "..."})        FLY             emit upstream (SSE streaming)
("GET", ".route.next")           GET             send(deep_copy(value))
("SET", ".route.next", [...])    SET             mutate metadata in-place
("DEL", ".headers.trace_id")     DEL             remove metadata field
None (bare yield)                 NOOP            send(None)
anything else                     PROTOCOL ERROR  raise, terminate
```

### 3.2 Handler interaction modes

| Handler type | VFS access (current) | ABI access (new) |
|---|---|---|
| Function (returns dict) | Can read/write VFS via `open()` | No metadata access — use generator if needed |
| Generator (yields dicts) | Can read/write VFS via `open()` | Uses ABI yields for metadata, bare dict yields for frames |

Function actors that currently use VFS for routing must become generators.
In practice, only compiler-generated routers do this — user handlers rarely
touch metadata directly.

---

## 4. Path Resolver

### 4.1 Grammar

```
path       := '.' segment+
segment    := dot_key | bracket
dot_key    := '.' IDENTIFIER
bracket    := '[' (INTEGER | SLICE) ']'
IDENTIFIER := [a-zA-Z_][a-zA-Z0-9_-]*
INTEGER    := '-'? [0-9]+
SLICE      := INTEGER? ':' INTEGER?
```

### 4.2 Examples

```
Path                    Resolves to
──────────────────────  ────────────────────────────────────
.route.next             message["route"]["next"]
.route.next[0]          message["route"]["next"][0]
.route.next[-1]         message["route"]["next"][-1]
.headers.x-asya-fan-in  message["headers"]["x-asya-fan-in"]
.status.error.type      message["status"]["error"]["type"]
.status.error.mro       message["status"]["error"]["mro"]
.id                     message["id"]
```

### 4.3 Slice semantics (SET only)

Slices use Python list slice assignment semantics:

```python
yield "SET", ".route.next[:0]", ["a", "b"]
# Equivalent to: message["route"]["next"][:0] = ["a", "b"]
# Effect: prepend ["a", "b"] to route.next
```

Slice access is a protocol error for GET and DEL.
Slice on non-list types is a protocol error.

### 4.4 Implementation sketch

```python
import re, copy

_PATH_RE = re.compile(
    r'\.([a-zA-Z_][a-zA-Z0-9_-]*)'   # .key
    r'|\[(-?\d+)\]'                    # [int]
    r'|\[(-?\d*):(-?\d*)\]'            # [start:stop]
)

_Dot = tuple[str, str]      # ("dot", key)
_Idx = tuple[str, int]      # ("idx", index)
_Slc = tuple[str, object]   # ("slc", slice(start, stop))

def _parse_path(path: str) -> list:
    if not path.startswith("."):
        raise ValueError(f"Path must start with '.': {path}")
    segments = []
    for m in _PATH_RE.finditer(path):
        if m.group(1) is not None:
            segments.append(("dot", m.group(1)))
        elif m.group(2) is not None:
            segments.append(("idx", int(m.group(2))))
        else:
            start = int(m.group(3)) if m.group(3) else None
            stop = int(m.group(4)) if m.group(4) else None
            segments.append(("slc", slice(start, stop)))
    if not segments:
        raise ValueError(f"Empty path: {path}")
    return segments


def _navigate(data: dict, segments: list):
    """Navigate to the node addressed by segments."""
    node = data
    for kind, val in segments:
        if kind == "dot":
            node = node[val]
        elif kind == "idx":
            node = node[val]
        else:
            raise ValueError("Slice only valid as terminal SET segment")
    return node


def _resolve_get(data: dict, segments: list):
    return copy.deepcopy(_navigate(data, segments))


def _resolve_set(data: dict, segments: list, value):
    parent = _navigate(data, segments[:-1]) if len(segments) > 1 else data
    kind, val = segments[-1]
    if kind == "dot":
        parent[val] = copy.deepcopy(value)
    elif kind == "idx":
        parent[val] = copy.deepcopy(value)
    elif kind == "slc":
        parent[val] = copy.deepcopy(value)  # slice assignment on list


def _resolve_del(data: dict, segments: list):
    parent = _navigate(data, segments[:-1]) if len(segments) > 1 else data
    kind, val = segments[-1]
    if kind == "dot":
        del parent[val]
    elif kind == "idx":
        del parent[val]
    else:
        raise ValueError("Slice not valid for DEL")
```

### 4.5 Auto-creation of intermediate dicts

SET auto-creates intermediate dicts when navigating. This eliminates the
need for `os.makedirs()` in generated code:

```python
# VFS: explicit directory creation
_os.makedirs(f"{_MSG_ROOT}/headers", exist_ok=True)
with open(f"{_MSG_ROOT}/headers/x-asya-fan-in", "w") as _f:
    _f.write(json.dumps({...}))

# ABI: just SET, intermediates are auto-created
yield "SET", ".headers.x-asya-fan-in", {...}
```

Implementation: during navigation for SET, if a dot-access key is missing,
create an empty dict:

```python
if kind == "dot":
    if val not in node:
        node[val] = {}
    node = node[val]
```

---

## 5. ABI Dispatch Engine

### 5.1 Context class

Replaces `_MessageVFS`. Same lifecycle (populate → use → snapshot → clear) but
simpler — just a dict holder with access control:

```python
class _AbiContext:
    def __init__(self, message: dict):
        route = message["route"]
        self.data = {
            "id": message.get("id", ""),
            "parent_id": message.get("parent_id", ""),
            "route": {
                "prev": list(route["prev"]),
                "curr": route["curr"],
                "next": list(route["next"]),
            },
            "headers": dict(message.get("headers") or {}),
            "status": copy.deepcopy(message.get("status") or {}),
        }
        self.input_route = route

    def snapshot(self) -> dict:
        return {
            "route_next": list(self.data["route"]["next"]),
            "headers": dict(self.data["headers"]),
            "status": copy.deepcopy(self.data.get("status") or {}),
        }
```

### 5.2 Access control

Whitelist approach — simpler than VFS's blacklist:

```python
def _check_set_access(path: str):
    if path.startswith(".route.next") or path.startswith(".headers"):
        return
    raise PermissionError(f"Cannot SET {path}")

def _check_del_access(path: str):
    if (path.startswith(".route.next")
            or path.startswith(".headers")
            or path.startswith(".status")):
        return
    raise PermissionError(f"Cannot DEL {path}")
```

| Path | GET | SET | DEL | Rationale |
|---|---|---|---|---|
| `.id` | read | deny | deny | Immutable message identity |
| `.parent_id` | read | deny | deny | Immutable fanout lineage |
| `.route.prev` | read | deny | deny | History is append-only (runtime manages) |
| `.route.curr` | read | deny | deny | Current actor is fixed for this invocation |
| `.route.next` | read | write | write | Handler's primary routing control |
| `.headers.*` | read | write | write | Mutable routing metadata |
| `.status.*` | read | deny | write | Readable + deletable (for exception clearing) |

Status is SET-denied but DEL-allowed because the except-dispatch router needs
to clear `.status.error` after matching an exception handler. Status is never
written by handlers — it's populated by the sidecar when forwarding error
responses.

### 5.3 Generator driver

Core dispatch loop — drives both sync and async generators:

```python
def _drive_generator(gen, ctx, on_fly=None):
    """Drive a sync generator, dispatching ABI commands."""
    frames = []
    send_val = None

    while True:
        try:
            yielded = gen.send(send_val)
        except StopIteration:
            break

        send_val = None

        if yielded is None:                                          # NOOP
            continue
        elif isinstance(yielded, dict):                              # EMIT
            frames.append(_build_frame(yielded, ctx.input_route, ctx.snapshot()))
        elif isinstance(yielded, tuple) and len(yielded) >= 2:
            verb = yielded[0]
            if verb == "FLY":                                        # FLY
                if on_fly:
                    on_fly(yielded[1])
            elif verb == "GET":                                      # GET
                segs = _parse_path(yielded[1])
                send_val = _resolve_get(ctx.data, segs)
            elif verb == "SET" and len(yielded) >= 3:                # SET
                _check_set_access(yielded[1])
                segs = _parse_path(yielded[1])
                _resolve_set(ctx.data, segs, yielded[2])
            elif verb == "DEL":                                      # DEL
                _check_del_access(yielded[1])
                segs = _parse_path(yielded[1])
                _resolve_del(ctx.data, segs)
            else:
                raise RuntimeError(f"ABI protocol error: unknown verb {verb!r}")
        else:
            raise RuntimeError(
                f"ABI protocol error: unexpected yield type {type(yielded).__name__}"
            )

    return frames
```

Async variant uses `asend()` and `StopAsyncIteration`. Same logic.

### 5.4 Integration with existing runtime

**Batch mode** (`_collect_payload_frames`, line 722):

```python
def _collect_payload_frames(message, user_func):
    ctx = _AbiContext(message)

    if inspect.isasyncgenfunction(user_func):
        return asyncio.run(_drive_async_generator(
            user_func(message["payload"]), ctx))

    if inspect.isgeneratorfunction(user_func):
        gen = user_func(message["payload"])
        # First yield to prime the generator
        return _drive_generator(gen, ctx)

    # Function actor — no ABI access
    result = _call_handler(user_func, message["payload"])
    if result is None:
        return []
    return [_build_frame(result, ctx.input_route, ctx.snapshot())]
```

**SSE streaming mode** (`_stream_sse_response`, line 1287):

```python
def _stream_sse_response(self, message, user_func):
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.end_headers()

    ctx = _AbiContext(message)

    def on_fly(payload):
        data = json.dumps({"payload": payload})
        self.wfile.write(f"event: upstream\ndata: {data}\n\n".encode())
        self.wfile.flush()

    def on_emit(frame):
        data = json.dumps(frame)
        self.wfile.write(f"event: downstream\ndata: {data}\n\n".encode())
        self.wfile.flush()

    try:
        if inspect.isasyncgenfunction(user_func):
            asyncio.run(_drive_async_generator_sse(
                user_func(message["payload"]), ctx, on_fly, on_emit))
        else:
            _drive_generator_sse(
                user_func(message["payload"]), ctx, on_fly, on_emit)
    except Exception as exc:
        logger.exception("Error during SSE streaming")
        error_data = json.dumps(_error_response("processing_error", exc))
        self.wfile.write(f"event: error\ndata: {error_data}\n\n".encode())
        self.wfile.flush()

    self.wfile.write(b"event: done\ndata: {}\n\n")
    self.wfile.flush()
```

The SSE driver differs from batch: instead of collecting frames into a list,
it emits each EMIT frame as `event: downstream` immediately via `on_emit`.
FLY frames go via `on_fly` as `event: upstream`. ABI commands (GET/SET/DEL)
are processed identically.

### 5.5 `_build_frame` — unchanged

`_build_frame` (line 704) already takes a state dict with `route_next`,
`headers`, `status`. It builds the shifted route and constructs the frame.
No changes needed — it works with both VFS snapshots and ABI context
snapshots because the snapshot format is identical.

---

## 6. Compiler Codegen Migration

All 10 router types need updating. Each router becomes a **generator** (uses
`yield` instead of `return`). The `_generate_msg_root_constant()` method and
`import os as _os` are removed.

### 6.1 Start router

**Before** (VFS):
```python
def start_flow(payload: dict) -> dict:
    """Entrypoint for flow 'flow'"""
    with open(f"{_MSG_ROOT}/route/next") as _f:
        _next_tail = _f.read().splitlines()
    _next = []
    _next.append(resolve("handler_a"))
    with open(f"{_MSG_ROOT}/route/next", "w") as _f:
        _f.write("\n".join(_next + _next_tail))
    return payload
```

**After** (ABI):
```python
def start_flow(payload: dict):
    """Entrypoint for flow 'flow'"""
    _next_tail = yield "GET", ".route.next"
    _next = []
    _next.append(resolve("handler_a"))
    yield "SET", ".route.next", _next + _next_tail
    yield payload
```

### 6.2 End router

**Before**: `open(..., "w").write("")` + `return payload`

**After**:
```python
def end_flow(payload: dict):
    """Exitpoint for flow 'flow'"""
    yield "SET", ".route.next", []
    yield payload
```

### 6.3 Sequential router (conditionals, mutations)

**Before**: Same VFS read/write pattern + `return payload`

**After**:
```python
def router_flow_line_5_seq(payload: dict):
    """Router for control flow and payload mutations"""
    p = payload
    _next_tail = yield "GET", ".route.next"
    _next = []

    p['processed'] = True

    if p['type'] == 'express':
        _next.append(resolve("express_handler"))
    else:
        _next.append(resolve("standard_handler"))

    yield "SET", ".route.next", _next + _next_tail
    yield payload
```

### 6.4 Fan-out router

Already a generator. Remove VFS file I/O, use ABI yields:

**Before**: `open(.../id).read()`, `open(.../route/next).read()`,
`os.makedirs(headers)`, `open(.../headers/x-asya-fan-in).write(json.dumps(...))`

**After**:
```python
def fanout_flow_line_10(payload: dict):
    """Fan-out router: dispatches to sub-agents and aggregator"""
    p = payload
    origin_id = yield "GET", ".id"
    _next_tail = yield "GET", ".route.next"
    _agg = resolve("fanin_flow_line_10")

    _slices = []
    _slices.append((resolve("analyzer"), p['text']))

    _n = len(_slices) + 1
    _fan_in = {
        "actor": _agg,
        "origin_id": origin_id,
        "slice_count": _n,
        "aggregation_key": "/analysis",
    }

    # Index 0: parent payload to aggregator
    yield "SET", ".route.next", [_agg, resolve("merge")] + _next_tail
    yield "SET", ".headers.x-asya-fan-in", {**_fan_in, "slice_index": 0}
    yield copy.deepcopy(p)

    # Indices 1..N: sub-agent slices
    for _i, (_actor, _payload) in enumerate(_slices):
        yield "SET", ".route.next", [_actor, _agg]
        yield "SET", ".headers.x-asya-fan-in", {**_fan_in, "slice_index": _i + 1}
        yield _payload
```

Key improvements:
- No `json.dumps()`/`json.loads()` — ABI works with native Python objects
- No `os.makedirs()` — SET auto-creates intermediate dicts
- `copy.deepcopy(p)` replaces `json.loads(json.dumps(p))` for parent payload

### 6.5 Loop-back router

**Before**: Read `route/prev` via file I/O, count occurrences

**After**:
```python
def router_flow_line_8_while_0(payload: dict):
    """Loop-back router: re-inserts loop actors into route (guarded)"""
    p = payload
    _next_tail = yield "GET", ".route.next"
    _next = []

    _self = resolve("router_flow_line_8_while_0")
    _prev = yield "GET", ".route.prev"
    if _prev.count(_self) >= _ASYA_MAX_LOOP_ITERATIONS:
        raise RuntimeError(
            f"Max loop iterations ({_ASYA_MAX_LOOP_ITERATIONS}) exceeded")

    if p['should_retry']:
        _next.append(resolve("process"))
        _next.append(resolve("router_flow_line_8_while_0"))

    yield "SET", ".route.next", _next + _next_tail
    yield payload
```

### 6.6 Try-enter router

**Before**: `os.makedirs` + `open(.../headers/_on_error, "w").write(...)`

**After**:
```python
def router_flow_try_enter_0(payload: dict):
    """Try-enter router: sets _on_error header and inserts try body"""
    _next_tail = yield "GET", ".route.next"
    _next = []

    yield "SET", ".headers._on_error", resolve("except_dispatch_0")

    _next.append(resolve("call_api"))
    _next.append(resolve("try_exit_0"))

    yield "SET", ".route.next", _next + _next_tail
    yield payload
```

### 6.7 Try-exit router

**Before**: `os.path.exists()` + `os.remove()` for `_on_error` header

**After**:
```python
def router_flow_try_exit_0(payload: dict):
    """Try-exit router: clears _on_error header (success path)"""
    _next_tail = yield "GET", ".route.next"
    _next = []

    headers = yield "GET", ".headers"
    if "_on_error" in headers:
        yield "DEL", ".headers._on_error"

    yield "SET", ".route.next", _next + _next_tail
    yield payload
```

### 6.8 Except-dispatch router

**Before**: Read `status/error/type` and `status/error/mro` via file I/O,
`shutil.rmtree(status/error)` to clear error state

**After**:
```python
def router_flow_except_dispatch_0(payload: dict):
    """Except-dispatch router: matches error type and routes to handler"""
    p = payload
    _next_tail = yield "GET", ".route.next"
    _next = []

    _error_type = yield "GET", ".status.error.type"
    _error_mro = yield "GET", ".status.error.mro"
    _all_types = [_error_type] + _error_mro

    if "ConnectionError" in _all_types:
        yield "DEL", ".status.error"
        _next.append(resolve("log_retry"))
    elif "ValueError" in _all_types:
        yield "DEL", ".status.error"
        pass
    else:
        _next.append(resolve("reraise_0"))

    yield "SET", ".route.next", _next + _next_tail
    yield payload
```

### 6.9 Reraise router

**Before**: Read `status/error/type` and `status/error/message` via file I/O

**After**:
```python
def router_flow_reraise_0(payload: dict):
    """Reraise router: raises RuntimeError for unhandled exceptions"""
    _error_type = yield "GET", ".status.error.type"
    _error_msg = yield "GET", ".status.error.message"
    raise RuntimeError(f"Unhandled exception {_error_type}: {_error_msg}")
```

Note: reraise is still a generator (uses `yield "GET"`) even though it never
yields a payload frame. It raises before reaching any EMIT yield.

### 6.10 Codegen changes summary

| Method | Lines (before) | Lines (after) | Key change |
|---|---|---|---|
| `_generate_msg_root_constant` | 5 | 0 | Removed entirely |
| `_generate_start_router` | 26 | 14 | `open()` → `yield "GET"/"SET"` |
| `_generate_end_router` | 10 | 7 | `open(w).write("")` → `yield "SET", [], []` |
| `_generate_router` | 44 | 34 | Same pattern |
| `_generate_fanout_router` | 94 | 55 | No json/os imports, native types |
| `_generate_loop_back_router` | 37 | 28 | `open(prev)` → `yield "GET"` |
| `_generate_try_enter_router` | 24 | 16 | No `makedirs` |
| `_generate_try_exit_router` | 29 | 17 | `path.exists + remove` → `GET + DEL` |
| `_generate_except_dispatch_router` | 65 | 42 | No `shutil.rmtree` |
| `_generate_reraise_router` | 12 | 8 | File reads → GETs |
| **Total** | **346** | **~221** | **-125 lines** |

Additional changes:
- Remove `import json as _json` for fan-out (no longer needed for header serialization)
- Remove `import os as _os` from generated code
- All routers change `-> dict:` to `:` (generators, no return annotation)
- All routers change `return payload` to `yield payload`
- `generate()` method: remove `_generate_msg_root_constant()` call, remove
  conditional `import json as _json`

---

## 7. What Gets Removed

### 7.1 Runtime removal inventory

| Component | Lines | File location |
|---|---|---|
| `ASYA_MSG_ROOT` constant | 83 | Remove |
| `_READ_ONLY_PATHS` | 322 | Remove |
| `_MessageVFS` class | 325-523 (~200 lines) | Remove |
| `_MsgVirtualFile` class | 525-590 (~65 lines) | Remove |
| `_msg_vfs` global | 594 | Remove |
| `_patched_open` | 604-612 | Remove |
| `_patched_listdir` | 615-620 | Remove |
| `_patched_path_exists` | 623-628 | Remove |
| `_patched_path_isdir` | 631-636 | Remove |
| `_patched_remove` | 639-644 | Remove |
| `_patched_makedirs` | 647-651 | Remove |
| `_patched_rmdir` | 654-658 | Remove |
| `_install_msg_hooks` | 661-690 (~30 lines) | Remove |
| VFS calls in `_collect_payload_frames` | 733, 743, 754, 763, 766 | Replace |
| VFS calls in `_stream_sse_response` | 1295, 1307 | Replace |
| VFS calls in `_emit_sse_event` | 1325-1335 | Replace |
| `partial: True` detection | 741, 752, 1325 | Replaced by FLY dispatch |
| `_install_msg_hooks()` call in `handle_requests` | 1361 | Remove |
| `msg_root` in `_log_env_vars` | 1350 | Remove reference |
| **Total removed** | **~370 lines** | |

### 7.2 Compiler removal

| Item | Location |
|---|---|
| `_generate_msg_root_constant()` | codegen.py:51-55 |
| `import os as _os` in generated code | All routers |
| `import json as _json` in generated code | Fan-out only |
| `import shutil` in generated code | Except-dispatch only |
| File I/O patterns in all 10 router generators | codegen.py:128-476 |

### 7.3 What is NOT removed

- `ASYA_MSG_ROOT` env var in injector — not set by injector (confirmed:
  injector sets `ASYA_SOCKET_DIR`, `ASYA_ACTOR_NAME`, `ASYA_NAMESPACE` etc.
  but NOT `ASYA_MSG_ROOT`)
- Socket communication (`/var/run/asya/`) — unrelated to VFS
- `_build_frame()` function — unchanged, works with ABI context snapshots
- `resolve()` function in generated code — VFS-independent
- SSE wire protocol (`event: upstream`, `event: downstream`) — unchanged

---

## 8. Implementation Phases

### Phase 1: Path resolver

**Scope**: ~90 lines of new code + ~100 lines of unit tests

- Implement `_parse_path()` tokenizer
- Implement `_resolve_get()`, `_resolve_set()`, `_resolve_del()`
- Implement `_navigate()` helper with auto-creation for SET
- Unit tests covering: dot access, index access, slice access (prepend,
  append, range), nested paths, access on missing keys (KeyError),
  index on non-list (TypeError), slice on non-list (TypeError)

**Deliverable**: Standalone module testable without runtime integration.

### Phase 2: ABI dispatch engine

**Scope**: ~80 lines of new code + ~150 lines of unit tests

- Implement `_AbiContext` class (populate from message, snapshot)
- Implement access control (`_check_set_access`, `_check_del_access`)
- Implement `_drive_generator()` (sync) and `_drive_async_generator()` (async)
- Implement SSE variants: `_drive_generator_sse()`, `_drive_async_generator_sse()`
- Unit tests covering: each ABI verb, access control violations, protocol
  errors (bad yield types), FLY in batch mode (skipped), FLY in SSE mode
  (emitted), mixed ABI + EMIT sequences, GET returns deep copy

**Deliverable**: ABI dispatch works for both batch and SSE modes.

### Phase 3: Runtime integration

**Scope**: ~50 lines changed in existing code

- Replace VFS calls in `_collect_payload_frames()` with ABI context + driver
- Replace VFS calls in `_stream_sse_response()` with ABI SSE driver
- Remove `_emit_sse_event()` (logic moves into SSE driver)
- Remove `_install_msg_hooks()` call from `handle_requests()`
- Keep VFS code present but unused (removed in Phase 5)

**Deliverable**: Runtime uses ABI dispatch. Existing tests may break (VFS
tests) but handler behavior tests should pass.

### Phase 4: Compiler codegen migration

**Scope**: ~300 lines changed in codegen.py

- Update all 10 router generators to emit ABI yields
- Remove `_generate_msg_root_constant()`
- Remove `import json as _json` conditional
- Update all generated router signatures: `-> dict` → generator (no annotation)
- Update `return payload` → `yield payload`
- Recompile all example flows in the repository
- Update compiler unit tests and snapshot tests

**Deliverable**: `asya flow compile` produces ABI-based routers.

### Phase 5: VFS removal

**Scope**: ~370 lines removed

- Remove `_MessageVFS` class
- Remove `_MsgVirtualFile` class
- Remove all patching functions and `_install_msg_hooks()`
- Remove `ASYA_MSG_ROOT` constant and `_READ_ONLY_PATHS`
- Remove `_msg_vfs` global
- Update or remove VFS-specific unit tests
- Update `_log_env_vars()` to remove `msg_root` reference

**Deliverable**: No VFS code remains. Runtime is ~200 lines shorter.

### Phase 6: Integration and component tests

**Scope**: Test updates

- Update integration tests that verify VFS behavior
- Update component tests (sidecar-runtime) — wire protocol is unchanged
  so most tests should pass without changes
- Verify fan-out tests work with ABI-based routers
- Verify try/except tests work with ABI-based routers

### Phase 7: Documentation

- Update AGENTS.md: remove VFS references, document ABI
- Close epic 1ixt (message metadata VFS) — superseded
- Update flow DSL documentation with ABI-based router examples

---

## 9. Testing Strategy

### 9.1 Path resolver tests (Phase 1)

```python
# Dot access
assert _resolve_get({"route": {"next": ["a"]}}, _parse_path(".route.next")) == ["a"]

# Index access
assert _resolve_get({"route": {"next": ["a", "b"]}}, _parse_path(".route.next[0]")) == "a"
assert _resolve_get({"route": {"next": ["a", "b"]}}, _parse_path(".route.next[-1]")) == "b"

# SET with slice (prepend)
data = {"route": {"next": ["c", "d"]}}
_resolve_set(data, _parse_path(".route.next[:0]"), ["a", "b"])
assert data["route"]["next"] == ["a", "b", "c", "d"]

# SET auto-creates intermediate dicts
data = {}
_resolve_set(data, _parse_path(".headers.trace_id"), "abc")
assert data == {"headers": {"trace_id": "abc"}}

# Deep copy on GET
data = {"route": {"next": ["a"]}}
result = _resolve_get(data, _parse_path(".route.next"))
result.append("mutated")
assert data["route"]["next"] == ["a"]  # original unchanged
```

### 9.2 ABI dispatch tests (Phase 2)

```python
# GET returns value
def gen(payload):
    prev = yield "GET", ".route.prev"
    payload["saw_prev"] = prev
    yield payload

ctx = _AbiContext({"route": {"prev": ["x"], "curr": "a", "next": []}, "payload": {}})
frames = _drive_generator(gen({}), ctx)
assert frames[0]["payload"]["saw_prev"] == ["x"]

# SET modifies route
def gen(payload):
    yield "SET", ".route.next", ["b", "c"]
    yield payload

ctx = _AbiContext({"route": {"prev": [], "curr": "a", "next": []}, "payload": {}})
frames = _drive_generator(gen({}), ctx)
assert frames[0]["route"]["curr"] == "b"
assert frames[0]["route"]["next"] == ["c"]

# FLY in batch mode — skipped
def gen(payload):
    yield "FLY", {"token": "hello"}  # skipped (no on_fly callback)
    yield payload

frames = _drive_generator(gen({}), ctx)
assert len(frames) == 1  # only the EMIT frame

# FLY in SSE mode — emitted
fly_events = []
def gen(payload):
    yield "FLY", {"token": "hello"}
    yield payload

_drive_generator(gen({}), ctx, on_fly=lambda p: fly_events.append(p))
assert fly_events == [{"token": "hello"}]

# Protocol error
def gen(payload):
    yield 42  # not dict, not tuple, not None

with pytest.raises(RuntimeError, match="protocol error"):
    _drive_generator(gen({}), ctx)

# Access control
def gen(payload):
    yield "SET", ".route.prev", ["evil"]

with pytest.raises(PermissionError):
    _drive_generator(gen({}), ctx)
```

### 9.3 Migration verification (Phase 3-4)

Existing tests that verify handler behavior (payload transformation, routing,
fan-out, try/except) should pass without modification. Only VFS-specific tests
(direct `_msg_vfs.read()` / `_msg_vfs.write()` calls) need updating.

The wire protocol between runtime and sidecar is unchanged:
- `event: downstream` with frame JSON → same format
- `event: upstream` with `{"payload": {...}}` → same format
- `event: done` → unchanged
- `event: error` → unchanged

Therefore, sidecar tests and integration tests should pass without changes.

---

## 10. Migration Guide for Handler Authors

### 10.1 Function actors (no VFS usage)

No changes needed. Function actors that just transform payload continue to
work identically.

### 10.2 Function actors that use VFS

Must become generator actors:

```python
# Before (VFS)
def router(payload):
    with open("/proc/asya/msg/route/next", "w") as f:
        f.write("step_a\nstep_b")
    return payload

# After (ABI)
def router(payload):
    yield "SET", ".route.next", ["step_a", "step_b"]
    yield payload
```

### 10.3 Generator actors with `partial: True`

Replace `partial: True` with FLY:

```python
# Before (VFS)
async def llm(payload):
    async for token in model.stream(payload["query"]):
        yield {"partial": True, "type": "text_delta", "token": token}
    payload["response"] = "full response"
    yield payload

# After (ABI)
async def llm(payload):
    async for token in model.stream(payload["query"]):
        yield "FLY", {"type": "text_delta", "token": token}
    payload["response"] = "full response"
    yield payload
```

### 10.4 Data format changes

| Operation | VFS format | ABI format |
|---|---|---|
| Read route.next | `"\n".join(list)` → `str` | `list` (native Python) |
| Write route.next | `"\n".join(list)` | `list` (native Python) |
| Read/write headers | JSON string for complex values | Native Python objects |
| Read status fields | String values | Native Python objects |

---

## 11. ADRs

### ADR-1: Generators required for metadata access

**Decision**: Only generator actors can use the ABI. Function actors have no
metadata access.

**Rationale**: The ABI operates via `yield`/`send()`, which is fundamentally
a generator mechanism. Providing an alternative for function actors (e.g.,
a context variable or parameter) would create two parallel access paths and
undermine the single-mechanism simplicity.

**Impact**: Compiler-generated routers (all use metadata) must be generators.
User handlers that don't touch metadata (majority) are unaffected.

### ADR-2: Path syntax — jq-like dots + Python slicing

**Decision**: Use `.foo.bar[0][:3]` syntax, not filesystem paths `/foo/bar`.

**Rationale**:
- More familiar to Python developers
- Enables slice syntax without path-encoding hacks
- No ambiguity with actual filesystem paths
- Native representation of dict/list navigation

**Alternatives considered**:
- Keep `/path/style` — confusing with actual filesystem paths
- JSONPath (`$.route.next`) — extra `$` prefix adds noise
- Dict access syntax (`["route"]["next"]`) — verbose, hard to type in yield

### ADR-3: Whitelist over blacklist for access control

**Decision**: SET and DEL use whitelist (only explicitly allowed paths), not
blacklist (deny specific paths).

**Rationale**: The blacklist approach (`_READ_ONLY_PATHS`) is fragile — new
message fields are writable by default. Whitelist ensures new fields are
read-only unless explicitly granted write access.

### ADR-4: FLY replaces `partial: True`

**Decision**: Streaming events use `yield "FLY", {...}` instead of
`yield {"partial": True, ...}`.

**Rationale**: See abi-protocol.md Section 11 "Why FLY instead of partial:
True". Separates control plane (tuple dispatch) from data plane (dict payload).
The runtime never inspects dict contents.

### ADR-5: Auto-creation of intermediate dicts for SET

**Decision**: `yield "SET", ".headers.x-asya-fan-in", {...}` auto-creates the
`headers` dict if it doesn't exist.

**Rationale**: Eliminates `os.makedirs()` boilerplate. If you're setting a
nested path, the intent is clear — intermediate containers should exist.

**Constraint**: Auto-creation only creates dicts (not lists). Setting
`.route.next[0]` when `route.next` doesn't exist is still an error — lists
must be explicitly created.
