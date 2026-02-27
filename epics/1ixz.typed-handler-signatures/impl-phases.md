# Implementation Phases: Typed Handler Signatures

> Epic: [[1ixz]] | RFC: [[rfc.md]]

## Pre-implementation: RFC fixes

Before starting, apply these corrections to `rfc.md`:

1. **VFS path**: Replace all `/tmp/msg/` references with `/proc/asya/msg/`
   (sections: non-goals, section 9, section 11). The VFS landed in epic 1ixt
   with `ASYA_MSG_ROOT=/proc/asya/msg`.

2. **Envelope mode**: Remove all `ASYA_HANDLER_MODE=envelope` discussion
   (section 9 third paragraph, section 11 last paragraph).
   Envelope mode was fully removed from the runtime — there is no transition
   period to handle.

3. **Env var naming**: Rename throughout:
   - `ASYA_HANDLER_INPUT` -> `ASYA_HANDLER_INPUT_KEY`
   - `ASYA_HANDLER_OUTPUT` -> `ASYA_HANDLER_OUTPUT_KEY`
   Aligns with ADK's `output_key` convention. Values remain JSONPath-like paths.

4. **Yield upstream partial protocol**: Section 7.2 proposes
   `yield Token(...), True` (tuple syntax), but the runtime uses
   `yield {"partial": True, ...}` (dict with `"partial"` key).
   Decision needed — options:
   - **(a)** Keep existing dict convention: typed models must be serialized
     to dict and merged with `{"partial": True}` before yielding upstream.
   - **(b)** Support both: tuple `(model, True)` detected by the runtime,
     existing dict convention still works. Runtime serializes the model and
     forwards as upstream event.
   - Recommendation: **(b)** — cleaner for typed handlers, backward-compatible.

---

## Phase 1: Core Typed Handler Signatures (single PR)

**Goal**: Full typed input/output support in `asya_runtime.py` with tests.
All handler forms from RFC section 6 working end-to-end.

### Tasks

| Task | Ref | Description |
|------|-----|-------------|
| Input extraction + deserialization | [[1ixz/1m4yo6]] | Signature introspection (`inspect.signature`, `typing.get_type_hints`), legacy single-dict detection, `ASYA_HANDLER_INPUT_KEY` path navigation, per-parameter extraction by name, type-based deserialization (Pydantic v1/v2 `.model_validate`/`.parse_obj`, `dataclass(**val)`, TypedDict passthrough, primitive passthrough). Error on missing required params. |
| Output merge + serialization | [[1ixz/1m8sym]] | `ASYA_HANDLER_OUTPUT_KEY` path navigation with auto-creation of intermediate dicts, return value serialization (`.model_dump`/`.dict`, `asdict`, passthrough), shallow merge (`dict.update`) at target path, scalar/list direct write at path. `None` return preserves abort semantics. |
| Generator/yield typed support | [[1ixz/1m6hk3]] | Extend yield handling to serialize typed return values (same serialization dispatcher as output merge). Support tuple `(model, True)` for upstream partials alongside existing `{"partial": True}` convention. Each yield frame serialized independently. |
| Tests | [[1ixz/1mnz5v]] | **Unit tests**: All 8 handler forms (RFC 6.1-6.8) — legacy dict, typed params + dict return, typed params + typed return, Pydantic input model, multiple typed params, dataclass, TypedDict, class-based. Edge cases: missing keys, optional params, nested input paths, nested output paths, scalar return, list return, `None` return. **Component tests**: Docker Compose with typed handler containers, end-to-end via Unix socket HTTP. |

### Dependency order

```
1m4yo6 (input) ─┐
                 ├──> 1m6hk3 (yield) ──> 1mnz5v (tests)
1m8sym (output) ─┘
```

Input and output can be implemented in parallel but yield depends on both
(it reuses the serialization/deserialization dispatchers). Tests validate
everything together.

### Files modified

| File | Changes |
|------|---------|
| `src/asya-runtime/asya_runtime.py` | New functions: `_introspect_handler()`, `_extract_input()`, `_deserialize_param()`, `_merge_output()`, `_serialize_return()`. Modified: `_call_handler()`, `_collect_payload_frames()`, `_handle_invoke()` startup introspection. New env vars: `ASYA_HANDLER_INPUT_KEY`, `ASYA_HANDLER_OUTPUT_KEY`. |
| `src/asya-runtime/tests/` | New test files for typed signatures (unit). |
| `src/asya-testing/asya_testing/handlers/` | New `typed.py` with example typed handlers for all forms. |
| `testing/component/runtime/` | New test cases and handler services for typed signatures. |

### Backward compatibility

- `def f(payload: dict) -> dict` detection: `len(params) == 1 and annotation in (dict, Dict, Dict[str, Any], dict[str, Any], Parameter.empty)` -> legacy mode, env vars ignored.
- All existing tests must pass without modification.
- No sidecar, gateway, or wire protocol changes.

---

## Phase 2: Schema Generation (single PR)

**Goal**: JSON Schema introspection from type annotations, exposed via
`GET /schema` on the runtime Unix socket. Enables gateway MCP tool
auto-discovery.

### Tasks

| Task | Ref | Description |
|------|-----|-------------|
| Schema generation + endpoint | [[1ixz/1m58xk]] | Implement `_generate_schema()`: Pydantic `.model_json_schema()`, dataclass/TypedDict annotation walking (Python type -> JSON Schema type mapping). Add `GET /schema` HTTP handler on Unix socket server. Return `{"input_schema": {...}, "output_schema": {...}}`. Include unit tests for schema generation and HTTP endpoint. |

### Dependency

Phase 2 depends on Phase 1 (uses the same introspection infrastructure).

### Files modified

| File | Changes |
|------|---------|
| `src/asya-runtime/asya_runtime.py` | New: `_generate_input_schema()`, `_generate_output_schema()`, `_python_type_to_json_schema()`. Modified: HTTP server to handle `GET /schema`. Schema cached at startup. |
| `src/asya-runtime/tests/` | Schema generation unit tests. |

### Future integration (out of scope)

- Sidecar forwarding schema to gateway on request
- Gateway consuming schemas for MCP `tools/list` responses
- XRD annotation for schema exposure opt-in

---

## Summary

| Phase | PR | Tasks | Scope |
|-------|----|-------|-------|
| 1 | Core typed signatures | 1m4yo6, 1m8sym, 1m6hk3, 1mnz5v | Input extraction, output merge, yield, tests |
| 2 | Schema generation | 1m58xk | JSON Schema + endpoint |

Total: **2 PRs**, **5 tasks**, all changes in `src/asya-runtime/` + test infrastructure.
