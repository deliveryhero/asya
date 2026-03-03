---
title: "Smart JSON serialization: support pydantic, dataclasses, and typed structures in runtime"
priority: 2
type: task
dependencies: []
tags:
  - type:feature
  - runtime
  - a2a
---

## Motivation

Actors working with A2A protocol types (via `a2a-python` or custom pydantic models)
currently must manually call `.model_dump()` before returning or yielding payloads.
This is tedious, error-prone, and creates friction for actors that want to use typed
structures throughout their handler code.

**Goal**: actors can use bare pydantic models, dataclasses, TypedDicts, and other
JSON-serializable-by-protocol objects directly in handler returns, yielded payloads,
and FLY events — the runtime handles serialization transparently.

**Cross-reference**: A2A RFC (1c0d) Section 5.3.3.

## Problem

Two barriers in `asya_runtime.py` prevent non-dict payload objects:

### Barrier 1: Payload detection (`_drive_generator`)

```python
elif isinstance(yielded, dict):       # pydantic BaseModel is NOT a dict
    frame = _build_frame(yielded, ...)
```

A yielded pydantic model falls through to `raise RuntimeError`.

### Barrier 2: JSON serialization

```python
json.dumps({"frames": frames})        # pydantic objects inside frames blow up
```

Standard `json.dumps` has no `default` handler for pydantic, dataclasses, etc.

**Note**: TypedDicts are already plain dicts at runtime — `isinstance(td, dict)`
returns `True`. No changes needed for TypedDict.

## Design

### Part 1: `_json_default` handler

A single duck-typed function, zero imports, Python 3.7+ compatible:

```python
def _json_default(obj):
    # Pydantic v2: mode='json' ensures datetime/UUID/Decimal → JSON natives
    if hasattr(obj, 'model_dump'):
        return obj.model_dump(mode='json')
    # Pydantic v1
    if hasattr(obj, 'dict') and hasattr(obj, '__fields__'):
        return obj.dict()
    # dataclasses
    if hasattr(obj, '__dataclass_fields__'):
        from dataclasses import asdict
        return asdict(obj)
    # namedtuple
    if hasattr(obj, '_asdict'):
        return obj._asdict()
    # common non-JSON types
    if hasattr(obj, 'isoformat'):       # datetime/date/time
        return obj.isoformat()
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode('ascii')
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    raise TypeError(f"Not JSON serializable: {type(obj).__name__}")
```

Replace all `json.dumps(...)` calls in the runtime with
`json.dumps(..., default=_json_default)`.

This handles **nested** pydantic objects inside dicts transparently:
```python
yield "FLY", {"a2a": TaskArtifactUpdateEvent(artifact=Artifact(...))}
# json.dumps traverses dict, hits pydantic value, calls _json_default,
# model_dump(mode='json') recursively converts all nested models
```

### Part 2: Broaden payload detection

In `_drive_generator` and `_drive_async_generator`, accept dict-like yielded
values:

```python
# Before:
elif isinstance(yielded, dict):

# After:
elif isinstance(yielded, dict) or hasattr(yielded, 'model_dump') \
        or hasattr(yielded, '__dataclass_fields__'):
```

This allows bare pydantic models as entire payload frames:
```python
yield MyResultModel(status="done", artifacts=[...])
```

### What stays the same

- Wire format: envelopes are still plain JSON — the serializer is syntactic sugar
- Sidecar, gateway, queues: never see pydantic objects
- TypedDict: already works (it's a dict)
- Plain dicts: no behavior change

## Key detail: `mode='json'`

`model_dump(mode='json')` (not just `model_dump()`) is critical. Without
`mode='json'`, pydantic returns Python objects (datetime, UUID, Decimal) that
would still fail at `json.dumps`. With `mode='json'`, everything comes back as
JSON-native types.

## Supported types (document in asya-runtime.md)

After implementation, update `docs/architecture/asya-runtime.md` with a
"Serialization" section documenting the supported types:

| Type | Mechanism | Notes |
|------|-----------|-------|
| `dict` | Native | Always worked |
| `TypedDict` | Native (is a dict) | Always worked |
| Pydantic v2 `BaseModel` | `model_dump(mode='json')` | Recursive for nested models |
| Pydantic v1 `BaseModel` | `.dict()` | Detected via `__fields__` |
| `@dataclass` | `dataclasses.asdict()` | stdlib |
| `NamedTuple` | `._asdict()` | stdlib |
| `datetime`/`date`/`time` | `.isoformat()` | ISO 8601 string |
| `bytes` | base64 encoding | Returns ASCII string |
| `set`/`frozenset` | `list()` | Converted to JSON array |
| `UUID` | Not yet supported | Add if needed |

**Not supported** (and should not be — these aren't payloads):
- Arbitrary classes without serialization protocol
- Generators, coroutines, callables
- File objects, sockets

## Implementation plan

1. Add `_json_default()` to `asya_runtime.py`
2. Replace all `json.dumps()` calls (grep shows ~6 call sites)
3. Broaden `isinstance(yielded, dict)` in `_drive_generator` and
   `_drive_async_generator`
4. Unit tests: pydantic v2 model, dataclass, namedtuple, mixed dict+pydantic,
   nested models, FLY with pydantic payload
5. Update `docs/architecture/asya-runtime.md` with supported types table

## Testing

- Return bare pydantic model → serialized correctly
- Return dict with pydantic values → serialized correctly
- Yield FLY with pydantic payload → SSE event serialized correctly
- Yield bare pydantic model as payload frame → frame built correctly
- Nested pydantic models (model containing model) → recursive serialization
- model_dump(mode='json') datetime handling → ISO 8601 string
- Unsupported type → clear TypeError with type name
- Plain dict (regression) → no behavior change
