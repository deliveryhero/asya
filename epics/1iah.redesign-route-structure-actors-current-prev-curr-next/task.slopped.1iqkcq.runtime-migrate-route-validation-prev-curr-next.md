---
title: "Runtime: migrate route validation to prev/curr/next"
priority: 1 # high
type: task
---

Migrate the runtime's route validation, shift logic, and helper functions from `{actors, current}` to `{prev, curr, next}`.

## Validation rewrite

**`src/asya-runtime/asya_runtime.py:285-311`** — `_validate_envelope()` route section:

```python
# BEFORE
if "actors" not in route: raise ValueError(...)
if "current" not in route: route["current"] = 0
if not isinstance(route["actors"], list): raise ValueError(...)
if not isinstance(route["current"], int): raise ValueError(...)
if len(route["actors"]) == 0: raise ValueError(...)
current_idx = route["current"]
if current_idx < 0 or current_idx > len(route["actors"]): raise ValueError(...)

# AFTER
for field in ("prev", "curr", "next"):
    if field not in route:
        raise ValueError(f"Missing required field '{field}' in route")
if not isinstance(route["prev"], list):
    raise ValueError("Field 'route.prev' must be a list")
if not isinstance(route["curr"], str):
    raise ValueError("Field 'route.curr' must be a string")
if not isinstance(route["next"], list):
    raise ValueError("Field 'route.next' must be a list")
```

## Envelope mode validation simplification

**`asya_runtime.py:317-349`** — processed-actors-preserved check:

```python
# BEFORE (complex index arithmetic)
input_actors = input_route.get("actors", [])
input_current = input_route.get("current", 0)
processed_actors = input_actors[:input_current + 1]
output_prefix = output_actors[:len(processed_actors)]
if output_prefix != processed_actors: raise ValueError(...)

# Check actor at input position unchanged
if input_current < len(route["actors"]):
    actual_current_actor = route["actors"][input_current]
    if actual_current_actor != expected_current_actor: raise ValueError(...)

# AFTER (direct field comparison)
if route["prev"] != input_route["prev"]:
    raise ValueError("Cannot modify route.prev (already-processed actors)")
if route["curr"] != input_route["curr"]:
    raise ValueError("Cannot modify route.curr (current actor)")
# route["next"] is freely writable — handler controls future routing
```

This is a major simplification: 30 lines of index-based validation → 4 lines of direct comparison.

## Helper function

**`asya_runtime.py:371-374`**:

```python
# BEFORE
def _get_current_actor(message):
    actors = message["route"]["actors"]
    current = message["route"]["current"]
    return actors[current]

# AFTER
def _get_current_actor(message):
    return message["route"]["curr"]
```

## Route increment (shift)

**`asya_runtime.py:489-490`** — called after handler returns in payload mode:

```python
# BEFORE
output_route = message["route"].copy()
output_route["current"] = message["route"]["current"] + 1

# AFTER
r = message["route"]
output_route = {
    "prev": r["prev"] + [r["curr"]],
    "curr": r["next"][0] if r["next"] else "",
    "next": r["next"][1:] if r["next"] else [],
    **({"metadata": r["metadata"]} if "metadata" in r else {}),
}
```

**Edge case**: When `r["next"]` is empty, `curr` becomes `""` and `next` stays `[]`. The sidecar detects this (empty `next` after shift) and routes to x-sink.

## Testing helper updates

**`src/asya-testing/asya_testing/handlers/envelope.py:45-46`**:

```python
# BEFORE
output_route["current"] = message["route"]["current"] + 1

# AFTER
r = message["route"]
output_route = {"prev": r["prev"] + [r["curr"]], "curr": r["next"][0], "next": r["next"][1:]}
```

**`envelope.py:114-115`** — invalid route test:

```python
# BEFORE
output_route["current"] = actors_length + 5

# AFTER
output_route["prev"] = ["tampered"]  # Modifying prev triggers validation error
```

## Runtime unit test updates

**`src/asya-runtime/tests/test_asya_runtime.py`**:
- Line 143+: All test message fixtures use `{"actors": [...], "current": 0}` → update to `{"prev": [], "curr": "...", "next": [...]}`
- Line 1208-1209: Route modification test — update to modify `next` instead of splicing `actors`
- All `receive_frames()` assertions checking route format

## Test plan

- Validation accepts well-formed `{prev, curr, next}` routes
- Validation rejects missing fields (prev, curr, next)
- Validation rejects wrong types (prev=str, curr=list, etc.)
- Envelope mode: modifying `prev` raises ValueError
- Envelope mode: modifying `curr` raises ValueError
- Envelope mode: modifying `next` is allowed
- Route shift produces correct output for single, multi, and empty-next routes
- Existing handler modes (payload, envelope) work with new format
- Generator handlers emit correct shifted route per frame

## References

- RFC: 1iah/rfc.md section 3.2
