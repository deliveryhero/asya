---
title: "Flow compiler: emit prev/curr/next route format"
priority: 2 # medium
type: task
dependencies:
  - 1iah/1iqkcq
---

Update the flow DSL code generator to emit routers using `{prev, curr, next}` route format. The core change: replace splice-insert `r['actors'][c+1:c+1] = _next` with prepend-to-next `r['next'] = _next + r['next']`.

## Code generator changes

**`src/asya-cli/asya_cli/flow/codegen.py`** — every router type has the same pattern:

### Common pattern (appears in 6 router types)

```python
# BEFORE (lines 115-124, 144-178, 192-214, 224-238, 248-265, 276-328)
lines.append("    r = message['route']")
lines.append("    c = r['current']")
# ... build _next list ...
lines.append("    r['actors'][c+1:c+1] = _next")
lines.append("    r['current'] = c + 1")

# AFTER
lines.append("    r = message['route']")
# ... build _next list ...
lines.append("    r['next'] = _next + r['next']")
```

The `c = r['current']` line is no longer needed — the compiler doesn't need the current index. It only prepends to `next`.

### Affected methods

| Method | Lines | Change |
|---|---|---|
| `_generate_start_router()` | 111-128 | Remove `c` variable, replace splice |
| `_generate_router()` | 139-182 | Remove `c` variable, replace splice |
| `_generate_loop_back_router()` | 184-218 | Remove `c`, replace splice, update loop guard |
| `_generate_try_enter_router()` | 220-242 | Remove `c`, replace splice |
| `_generate_try_exit_router()` | 244-269 | Remove `c`, replace splice |
| `_generate_except_dispatch_router()` | 271-332 | Remove `c`, replace splice |

### Loop guard change

**`codegen.py:202`**:

```python
# BEFORE
lines.append("    if r['actors'][:c].count(_self) >= _ASYA_MAX_LOOP_ITERATIONS:")

# AFTER
lines.append("    if r['prev'].count(_self) >= _ASYA_MAX_LOOP_ITERATIONS:")
```

### End router (no change)

`_generate_end_router()` (line 130-137) just returns `message` unchanged — no route manipulation.

### Reraise router (no change)

`_generate_reraise_router()` (line 334-344) raises RuntimeError — no route manipulation.

## Regenerate test fixtures

All compiled router fixtures in `src/asya-testing/asya_testing/flows/` must be regenerated:

```bash
# For each flow in src/asya-testing/asya_testing/flows/*/
asya flow compile <flow>.py --output-dir <flow>/compiled/ --overwrite
```

Flows to regenerate:
- `nested_if/`
- Any other flow directories in `src/asya-testing/asya_testing/flows/`

Also regenerate the example flows in `examples/flows/` if they have compiled output.

## Crew sink handler

**`src/asya-crew/asya_crew/sink.py:122`**:

```python
# BEFORE
message["route"] = {"actors": hooks, "current": 0}

# AFTER
message["route"] = {"prev": [], "curr": hooks[0], "next": hooks[1:]}
```

Update docstring at line 33 to show new message format.

## Playground test fixtures

**`deploy/helm-charts/asya-playground/templates/testing-actors/k6-scripts-configmap.yaml:36`**:

```javascript
// BEFORE
route: { actors: [actor], current: 0 },

// AFTER
route: { prev: [], curr: actor, next: [] },
```

## Documentation updates

- `docs/architecture/asya-flow.md` — update generated code examples (lines 262-287)
- `docs/architecture/protocols/actor-actor.md` — update message format examples
- `docs/architecture/asya-runtime.md` — update route references
- `AGENTS.md` — update Message Protocol section

## Test plan

- All flow compiler unit tests pass (`src/asya-cli/tests/flow/`)
- Generated routers use `r['next'] = _next + r['next']` (not splice)
- Generated routers do NOT reference `r['current']` or `r['actors']`
- Loop guard checks `r['prev'].count(...)` instead of `r['actors'][:c].count(...)`
- Regenerated fixtures match expected output
- Sink handler routes to hooks with new format

## References

- RFC: 1iah/rfc.md section 3.5
