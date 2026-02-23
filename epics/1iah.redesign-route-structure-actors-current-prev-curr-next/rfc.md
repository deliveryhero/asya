# RFC: Route Structure Redesign — `{actors, current}` → `{prev, curr, next}`

**Date**: 2026-02-23
**Epic**: 1iah
**Source**: 1ixt/rfc.md section 1.1 (canonical route schema definition)

---

## 1. Problem Statement

The current route format uses an index-based traversal scheme:

```json
{"route": {"actors": ["a", "b", "c"], "current": 0}}
```

This has several problems:

1. **Splice-based routing is fragile** — the flow compiler generates `r['actors'][c+1:c+1] = [...]` to insert actors, which is error-prone and hard to reason about
2. **Validation is complex** — runtime must check that `actors[0:current+1]` is preserved, requiring index arithmetic and boundary checks
3. **No separation of history and future** — you can't tell which actors already processed vs which are pending without scanning the array up to `current`
4. **Progress calculation requires both fields** — gateway needs `len(actors)` and `current` to compute percentage, which couples the progress API to the internal route format

## 2. Target Format

```json
{
  "route": {
    "prev": ["a", "b"],
    "curr": "c",
    "next": ["d", "e"]
  }
}
```

| Field  | Type       | Mutability  | Meaning                         |
|--------|------------|-------------|---------------------------------|
| `prev` | `list[str]`| read-only   | Actors that already processed   |
| `curr` | `str`      | read-only   | Actor currently processing      |
| `next` | `list[str]`| read-write  | Actors remaining after current  |

### Route shift (performed by runtime after handler returns)

```
Before:  prev=["a"],    curr="b",  next=["c", "d"]
After:   prev=["a","b"], curr="c", next=["d"]
```

When `next` is empty after shift → sidecar routes to `x-sink`.

### Key simplifications

| Concern | Before (`actors/current`) | After (`prev/curr/next`) |
|---------|--------------------------|--------------------------|
| Insert future actors | `r['actors'][c+1:c+1] = [...]` | `r['next'] = [...] + r['next']` |
| Get current actor | `r['actors'][r['current']]` | `r['curr']` |
| Get next actor | `r['actors'][r['current']+1]` | `r['next'][0]` |
| Has more actors? | `r['current']+1 < len(r['actors'])` | `len(r['next']) > 0` |
| Validation | Check `actors[0:current+1]` preserved | Check `prev` and `curr` unchanged |
| Progress % | `current / len(actors)` | `len(prev) / (len(prev) + 1 + len(next))` |
| Loop guard | `r['actors'][:c].count(self)` | `r['prev'].count(self)` |

---

## 3. Migration Scope

### 3.1 Sidecar (Go) — `src/asya-sidecar/`

**Struct definition** (`pkg/messages/message.go:61-66`):
```go
// BEFORE
type Route struct {
    Actors   []string               `json:"actors"`
    Current  int                    `json:"current"`
    Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// AFTER
type Route struct {
    Prev     []string               `json:"prev"`
    Curr     string                 `json:"curr"`
    Next     []string               `json:"next"`
    Metadata map[string]interface{} `json:"metadata,omitempty"`
}
```

**Methods** (`pkg/messages/message.go:93-121`):
```go
// BEFORE                              // AFTER
func (r *Route) GetCurrentActor()      r.Curr
func (r *Route) GetNextActor()         if len(r.Next) > 0 { r.Next[0] }
func (r *Route) HasNextActor()         len(r.Next) > 0
func (r *Route) IncrementCurrent()     Route{Prev: append(r.Prev, r.Curr), Curr: r.Next[0], Next: r.Next[1:]}
```

**Router logic** (`internal/router/router.go`):
- All `route.Actors[route.Current]` → `route.Curr`
- All `route.Actors[route.Current+1]` → `route.Next[0]`
- All `route.HasNextActor()` → `len(route.Next) > 0`
- Error payload struct (line 1104-1110): update inline struct
- Final status payload (line 1159-1160): `finalPayload["actors"]` → use prev/curr/next

**Progress reporter** (`internal/progress/reporter.go:41-48`):
```go
// BEFORE
type ProgressUpdate struct {
    Actors          []string       `json:"actors"`
    CurrentActorIdx int            `json:"current_actor_idx"`
    ...
}

// AFTER
type ProgressUpdate struct {
    Prev   []string       `json:"prev"`
    Curr   string         `json:"curr"`
    Next   []string       `json:"next"`
    ...
}
```

Progress percentage is now calculated by the gateway from `len(prev) / (len(prev) + 1 + len(next))`.

### 3.2 Runtime (Python) — `src/asya-runtime/asya_runtime.py`

**Validation** (lines 285-350):
```python
# BEFORE
if "actors" not in route: raise ValueError(...)
if "current" not in route: route["current"] = 0

# AFTER
for field in ("prev", "curr", "next"):
    if field not in route:
        raise ValueError(f"Missing required field '{field}' in route")
if not isinstance(route["prev"], list): raise ValueError(...)
if not isinstance(route["curr"], str): raise ValueError(...)
if not isinstance(route["next"], list): raise ValueError(...)
```

**Envelope mode validation** (lines 317-349):
```python
# BEFORE: check actors[0:current+1] preserved
processed_actors = input_actors[:input_current + 1]
output_prefix = output_actors[:len(processed_actors)]
if output_prefix != processed_actors: raise ValueError(...)

# AFTER: check prev and curr unchanged (simpler)
if route["prev"] != input_route["prev"]: raise ValueError("Cannot modify prev")
if route["curr"] != input_route["curr"]: raise ValueError("Cannot modify curr")
```

**Helper** (lines 371-374):
```python
# BEFORE
def _get_current_actor(message):
    return message["route"]["actors"][message["route"]["current"]]

# AFTER
def _get_current_actor(message):
    return message["route"]["curr"]
```

**Route increment** (lines 489-490):
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
}
```

### 3.3 Gateway (Go) — `src/asya-gateway/`

**Types** (`pkg/types/task.go:55-60`):
Same struct change as sidecar. Note: the gateway has its OWN `Route` struct (duplicate definition). Both must be updated.

**Database schema** (`db/deploy/001_initial_schema.sql:9-10`):
```sql
-- BEFORE
route_actors TEXT[] NOT NULL,
route_current INTEGER NOT NULL DEFAULT 0,

-- AFTER
route_prev TEXT[] NOT NULL DEFAULT '{}',
route_curr TEXT NOT NULL,
route_next TEXT[] NOT NULL DEFAULT '{}',
```

Requires a database migration script (`002_route_format.sql`):
```sql
ALTER TABLE tasks ADD COLUMN route_prev TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE tasks ADD COLUMN route_curr TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN route_next TEXT[] NOT NULL DEFAULT '{}';

-- Migrate data
UPDATE tasks SET
    route_prev = route_actors[1:route_current],
    route_curr = route_actors[route_current + 1],
    route_next = route_actors[route_current + 2:];

ALTER TABLE tasks DROP COLUMN route_actors;
ALTER TABLE tasks DROP COLUMN route_current;
```

**Progress calculation** (`internal/mcp/handlers.go:364-416`):
```go
// BEFORE
totalActors := len(actors)
newProgress := (float64(progress.CurrentActorIdx)*100 + statusWeight) / float64(totalActors)

// AFTER
totalActors := len(progress.Prev) + 1 + len(progress.Next)
actorIdx := len(progress.Prev)
newProgress := (float64(actorIdx)*100 + statusWeight) / float64(totalActors)
```

**All SQL queries** in `internal/taskstore/pg_store.go`:
- Line 134: INSERT → use route_prev, route_curr, route_next
- Lines 174-175: SELECT → read route_prev, route_curr, route_next
- Line 381: UPDATE → update route columns

**Helm chart DB test** (`deploy/helm-charts/asya-gateway/templates/tests/test-db-schema.yaml:61,82`):
Update REQUIRED_COLUMNS and INSERT statements.

### 3.4 Crew (Python) — `src/asya-crew/`

**Sink handler** (`asya_crew/sink.py:122`):
```python
# BEFORE
message["route"] = {"actors": hooks, "current": 0}

# AFTER
message["route"] = {"prev": [], "curr": hooks[0], "next": hooks[1:]}
```

**Sink docstring** (line 33): Update message structure example.

### 3.5 Flow Compiler — `src/asya-cli/asya_cli/flow/codegen.py`

**Every router type** uses this pattern (appears at lines 115-124, 144-178, 192-214, 224-238, 248-265, 276-328):
```python
# BEFORE (splice-insert)
lines.append("    r = message['route']")
lines.append("    c = r['current']")
lines.append("    r['actors'][c+1:c+1] = _next")
lines.append("    r['current'] = c + 1")

# AFTER (prepend to next)
lines.append("    r = message['route']")
lines.append("    r['next'] = _next + r['next']")
```

No more `c = r['current']` — the compiler doesn't need the current index at all. It only appends to `next`.

**Loop guard** (line 202):
```python
# BEFORE
lines.append("    if r['actors'][:c].count(_self) >= _ASYA_MAX_LOOP_ITERATIONS:")

# AFTER
lines.append("    if r['prev'].count(_self) >= _ASYA_MAX_LOOP_ITERATIONS:")
```

**All generated router test fixtures** in `src/asya-testing/asya_testing/flows/` must be regenerated after the codegen change.

### 3.6 Testing Utilities — `src/asya-testing/`

**Envelope helpers** (`asya_testing/handlers/envelope.py:45-46, 114-115`):
```python
# BEFORE
output_route["current"] = message["route"]["current"] + 1

# AFTER
r = message["route"]
output_route = {"prev": r["prev"] + [r["curr"]], "curr": r["next"][0], "next": r["next"][1:]}
```

### 3.7 Documentation

- `docs/architecture/protocols/actor-actor.md` — update message examples
- `docs/architecture/asya-flow.md` — update generated code examples
- `docs/architecture/asya-runtime.md` — update route references
- `AGENTS.md` — update message protocol section

### 3.8 Integration & E2E Tests

All test files creating messages with `{"actors": [...], "current": ...}` must switch to `{"prev": [...], "curr": "...", "next": [...]}`. This includes:
- `src/asya-sidecar/internal/router/router_test.go` (multiple test structs)
- `src/asya-sidecar/internal/router/router_on_error_test.go`
- `src/asya-gateway/internal/mcp/progress_tracking_test.go`
- `src/asya-gateway/internal/taskstore/pg_store_bugs_test.go`
- `testing/component/gateway/tests_go/taskstore/pg_store_test.go`
- `testing/integration/gateway/tests/taskstore/pg_store_test.go`
- `deploy/helm-charts/asya-playground/templates/testing-actors/k6-scripts-configmap.yaml`

---

## 4. Migration Strategy

**Big-bang, not incremental.** The route format is a wire protocol — there's no way to support both formats simultaneously without adding complexity everywhere. All components must switch at once.

**Order**:
1. Sidecar Go struct + methods (everything compiles against new struct)
2. Runtime Python validation + shift (both sides speak new format)
3. Gateway types + DB migration + progress calculation
4. Flow compiler codegen + regenerate fixtures
5. Crew sink handler
6. Documentation
7. All tests updated throughout each step

Steps 1 and 2 can be done in parallel (different languages, different repos of concern). Step 3 depends on step 1 (shared struct). Step 4 depends on step 2 (Python code). Steps 5-7 are cleanup.

---

## 5. Backward Compatibility

**None.** This is a breaking change. All components must deploy simultaneously. The `Metadata` field on Route is preserved unchanged.
