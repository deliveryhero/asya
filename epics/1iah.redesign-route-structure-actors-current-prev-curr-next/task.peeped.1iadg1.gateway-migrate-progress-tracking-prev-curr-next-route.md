---
title: "Gateway: migrate progress tracking to prev/curr/next route"
priority: 2 # medium
type: task
dependencies:
  - 1iah/1ikdzb
---


Migrate gateway types, database schema, progress calculation, and task store queries from `{actors, current}` to `{prev, curr, next}`.

## Type changes

**`src/asya-gateway/pkg/types/task.go:55-60`** — Route struct:

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

**`task.go:83-86`** — TaskUpdate struct:

```go
// BEFORE
Actors          []string   `json:"actors,omitempty"`
CurrentActorIdx *int       `json:"current_actor_idx,omitempty"`

// AFTER
Prev []string `json:"prev,omitempty"`
Curr string   `json:"curr,omitempty"`
Next []string `json:"next,omitempty"`
```

**`task.go:115-122`** — ProgressUpdate struct:

```go
// BEFORE
Actors          []string `json:"actors"`
CurrentActorIdx int      `json:"current_actor_idx"`

// AFTER
Prev []string `json:"prev"`
Curr string   `json:"curr"`
Next []string `json:"next"`
```

**`task.go:34-53`** — Task struct: `CurrentActorIdx int` field → derive from `len(Route.Prev)`. `TotalActors int` → derive from `len(Prev) + 1 + len(Next)`.

## Database migration

**New file: `src/asya-gateway/db/deploy/002_route_format.sql`**:

```sql
BEGIN;

ALTER TABLE tasks ADD COLUMN route_prev TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE tasks ADD COLUMN route_curr TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN route_next TEXT[] NOT NULL DEFAULT '{}';

-- Migrate existing data (PostgreSQL arrays are 1-indexed)
UPDATE tasks SET
    route_prev = route_actors[1:route_current],
    route_curr = COALESCE(route_actors[route_current + 1], ''),
    route_next = route_actors[route_current + 2:array_length(route_actors, 1)];

ALTER TABLE tasks DROP COLUMN route_actors;
ALTER TABLE tasks DROP COLUMN route_current;

COMMIT;
```

Also create `db/revert/002_route_format.sql` and `db/verify/002_route_format.sql`.

## Progress calculation

**`src/asya-gateway/internal/mcp/handlers.go:364-416`**:

```go
// BEFORE
totalActors := len(actors)
newProgress := (float64(progress.CurrentActorIdx)*100 + statusWeight) / float64(totalActors)

// AFTER
totalActors := len(progress.Prev) + 1 + len(progress.Next)
actorIdx := len(progress.Prev)  // Current actor is at index = len(prev)
newProgress := (float64(actorIdx)*100 + statusWeight) / float64(totalActors)
```

The progress comparison logic (`task.Route.Actors` vs `progress.Actors` at lines 388-394) becomes:
```go
// BEFORE: compare actors list length
if len(progress.Actors) > len(actors) { actors = progress.Actors }

// AFTER: compare total route length
taskTotal := len(task.Route.Prev) + 1 + len(task.Route.Next)
progressTotal := len(progress.Prev) + 1 + len(progress.Next)
if progressTotal > taskTotal {
    // Route was extended by an envelope-mode actor
}
```

## Task store queries

**`src/asya-gateway/internal/taskstore/pg_store.go`**:
- Line 134: INSERT — `route_actors, route_current` → `route_prev, route_curr, route_next`
- Lines 174-175: SELECT — read new columns
- Line 381: UPDATE — `route_actors = COALESCE($5, route_actors)` → update prev/curr/next

## MCP handler structs

**`src/asya-gateway/internal/mcp/handlers.go:112-115`** — CreateTask request:

```go
// BEFORE
var createReq struct {
    Actors  []string `json:"actors"`
    Current int      `json:"current"`
}

// AFTER
var createReq struct {
    Prev []string `json:"prev"`
    Curr string   `json:"curr"`
    Next []string `json:"next"`
}
```

**`handlers.go:485-487`** — task response struct: update field names.

## Consumer error parsing

**`src/asya-gateway/internal/consumer/consumer.go:91-94`**:

```go
// BEFORE
Route struct {
    Actors   []string               `json:"actors"`
    Current  int                    `json:"current"`
    Metadata map[string]interface{} `json:"metadata"`
}

// AFTER
Route struct {
    Prev     []string               `json:"prev"`
    Curr     string                 `json:"curr"`
    Next     []string               `json:"next"`
    Metadata map[string]interface{} `json:"metadata"`
}
```

## Helm chart test

**`deploy/helm-charts/asya-gateway/templates/tests/test-db-schema.yaml`**:
- Line 61: `REQUIRED_COLUMNS` — replace `route_actors route_current` with `route_prev route_curr route_next`
- Line 82: INSERT statement — use new columns

## Test updates

- `internal/mcp/progress_tracking_test.go:357-407` — route update tests
- `internal/taskstore/pg_store_bugs_test.go:89-99` — route fields
- `testing/component/gateway/tests_go/taskstore/pg_store_test.go:71-74`
- `testing/integration/gateway/tests/taskstore/pg_store_test.go:75-78`

## Test plan

- DB migration script runs without errors on existing data
- Progress calculation produces correct percentages with new format
- Extended route detection works (envelope-mode actor adds actors to `next`)
- CreateTask endpoint accepts new format
- Final status endpoint returns new format
- All existing gateway unit, component, and integration tests pass

## References

- RFC: 1iah/rfc.md section 3.3
