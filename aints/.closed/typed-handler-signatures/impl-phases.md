# Implementation Phases: Typed Handler Signatures

> Epic: [[1ixz]] | RFC: [[rfc.md]]

## Design decisions

All decisions finalized and applied to the RFC:

1. **Env var names**: `ASYA_PARAMS_AT` / `ASYA_RESULT_AT`
   - "params" = function parameters (matches `inspect.signature().parameters`)
   - "result" = function return value
   - "_AT" suffix reads naturally: "params at .context", "result at .weather"

2. **Path syntax**: Reduced jq (not JSON Pointer, not JSONPath)
   - `.` = root, `.key` = child, `.key.subkey` = nested, `.[-1]` = last element
   - No VFS collision (`.key` vs `/proc/asya/msg/...`)
   - Shell-safe (no `$` expansion like JSONPath)
   - jq is well-known in the K8s ecosystem
   - Only single-location addressing (no wildcards/filters/slicing)

3. **Yield upstream partials**: Keep existing `{"partial": True}` convention only
   - No tuple `(model, True)` syntax
   - Typed models for upstream partials must be manually serialized to dict
     with `"partial": True` merged in

4. **No legacy detection**: All parameters extracted uniformly by name,
   regardless of type annotation. `dict` parameters are not special-cased.
   No `self.is_legacy` or mode branching. Existing `def f(payload: dict)`
   handlers must adapt (rename param or use `**kwargs`).

5. **Configurable merge strategy**: `ASYA_RESULT_MERGE` env var with two modes:
   - `shallow` (default): `target.update(result)` — top-level key merge
   - `deep`: recursive merge — nested dicts merged, scalars/lists overwritten

6. **Stale references removed**: `/tmp/msg/` -> `/proc/asya/msg/`,
   envelope mode discussion deleted (already removed from runtime)

---

## Phase 1: Core Typed Handler Signatures (single PR)

**Goal**: Full typed input/output support in `asya_runtime.py` with tests.
All handler forms from RFC section 6 working end-to-end.

### Tasks

| Task | Ref | Description |
|------|-----|-------------|
| Input extraction + deserialization | [[1m4y]] | Signature introspection (`inspect.signature`, `typing.get_type_hints`), legacy single-dict detection, `ASYA_PARAMS_AT` jq-style path navigation, per-parameter extraction by name, type-based deserialization (Pydantic v1/v2 `.model_validate`/`.parse_obj`, `dataclass(**val)`, TypedDict passthrough, primitive passthrough). Error on missing required params. |
| Output merge + serialization | [[1m8s]] | `ASYA_RESULT_AT` jq-style path navigation with auto-creation of intermediate dicts, return value serialization (`.model_dump`/`.dict`, `asdict`, passthrough), configurable merge via `ASYA_RESULT_MERGE` (shallow: `dict.update`, deep: recursive), scalar/list direct write at path. `None` return preserves abort semantics. |
| Generator/yield typed support | [[1m6h]] | Extend yield handling to serialize typed return values (same serialization dispatcher as output merge). Upstream partials use existing `{"partial": True}` convention unchanged. Each yield frame serialized independently. |
| Tests | [[1mnz]] | **Unit tests**: All 8 handler forms (RFC 6.1-6.8) -- legacy dict, typed params + dict return, typed params + typed return, Pydantic input model, multiple typed params, dataclass, TypedDict, class-based. Edge cases: missing keys, optional params, nested input paths, nested output paths, scalar return, list return, `None` return, array index paths. **Component tests**: Docker Compose with typed handler containers, end-to-end via Unix socket HTTP. |

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
| `src/asya-runtime/asya_runtime.py` | New functions: `_introspect_handler()`, `_parse_jq_path()`, `_navigate_path()`, `_extract_input()`, `_deserialize_param()`, `_merge_output()`, `_deep_merge()`, `_serialize_return()`. Modified: `_call_handler()`, `_collect_payload_frames()`, `_handle_invoke()` startup introspection. New env vars: `ASYA_PARAMS_AT`, `ASYA_RESULT_AT`, `ASYA_RESULT_MERGE`. |
| `src/asya-runtime/tests/` | New test files for typed signatures (unit). |
| `src/asya-testing/asya_testing/handlers/` | New `typed.py` with example typed handlers for all forms. |
| `testing/component/runtime/` | New test cases and handler services for typed signatures. |

### Backward compatibility

- No legacy detection — all parameters extracted uniformly by name.
- Existing `def f(payload: dict)` handlers need minor migration (rename param or use `**kwargs`).
- Existing tests for handler invocation will need updates to match new extraction behavior.
- No sidecar, gateway, or wire protocol changes.

---

## Phase 2: Schema Generation (single PR)

**Goal**: JSON Schema introspection from type annotations, exposed via
`GET /schema` on the runtime Unix socket. Enables gateway MCP tool
auto-discovery.

### Tasks

| Task | Ref | Description |
|------|-----|-------------|
| Schema generation + endpoint | [[1m58]] | Implement `_generate_schema()`: Pydantic `.model_json_schema()`, dataclass/TypedDict annotation walking (Python type -> JSON Schema type mapping). Add `GET /schema` HTTP handler on Unix socket server. Return `{"input_schema": {...}, "output_schema": {...}}`. Include unit tests for schema generation and HTTP endpoint. |

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

## Phase 3: Documentation (single PR)

### Tasks

| Task | Ref | Description |
|------|-----|-------------|
| Update docs | [[1mbk]] | Update `docs/` with typed handler signature guide: env vars, handler forms, deployment examples, migration path, jq path syntax reference. |

### Dependency

Phase 3 depends on Phase 1 (documents the implemented feature).

---

## Summary

| Phase | PR | Tasks | Scope |
|-------|----|-------|-------|
| 1 | Core typed signatures | 1m4yo6, 1m8sym, 1m6hk3, 1mnz5v | Input extraction, output merge, yield, tests |
| 2 | Schema generation | 1m58xk | JSON Schema + endpoint |
| 3 | Documentation | 1mbksn | docs/ updates |

Total: **3 PRs**, **6 tasks**, core changes in `src/asya-runtime/` + test infrastructure + docs.
