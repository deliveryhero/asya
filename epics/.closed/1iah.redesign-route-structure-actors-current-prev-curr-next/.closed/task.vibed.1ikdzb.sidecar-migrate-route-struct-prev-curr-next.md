---
title: "Sidecar: migrate Route struct to prev/curr/next"
priority: 1 # high
type: task
---





Migrate the sidecar's Route struct and all dependent routing logic from `{Actors, Current}` to `{Prev, Curr, Next}`.

## Struct change

**`src/asya-sidecar/pkg/messages/message.go:61-66`**:

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

## Method updates

**`message.go:93-121`** — all four methods:

| Method | Before | After |
|---|---|---|
| `GetCurrentActor()` | `r.Actors[r.Current]` | `r.Curr` |
| `GetNextActor()` | `r.Actors[r.Current+1]` | `r.Next[0]` (or `""` if empty) |
| `HasNextActor()` | `r.Current+1 < len(r.Actors)` | `len(r.Next) > 0` |
| `IncrementCurrent()` | `Route{Actors: r.Actors, Current: r.Current+1}` | `Route{Prev: append(r.Prev, r.Curr), Curr: r.Next[0], Next: r.Next[1:]}` |

## Router logic updates

**`src/asya-sidecar/internal/router/router.go`**:

All `route.Actors[route.Current]` references → `route.Curr`. Grep for `\.Actors` and `\.Current` to find all locations.

Specific locations:
- **Error payload struct** (line 1104-1110): inline struct has `Actors []string` and `Current int` — update to `Prev`, `Curr`, `Next`
- **Error payload extraction** (lines 1118-1127): `payload.Route.Actors` / `payload.Route.Current` → use new fields
- **Final status payload** (line 1159): `finalPayload["actors"] = route.Actors` → emit prev/curr/next
- **Final status actor name** (line 1125): `route.Actors[currentIdx]` → `route.Curr`

## Progress reporter updates

**`src/asya-sidecar/internal/progress/reporter.go:41-48`**:

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

Update all `ReportProgress()` call sites to pass `Prev`/`Curr`/`Next` instead of `Actors`/`CurrentActorIdx`.

**`reporter.go:150-153`** — `CreateTaskPayload` struct: same field changes.

## Test updates

- `pkg/messages/message_test.go:127-128` — route immutability tests
- `internal/router/router_test.go:420-423` — test struct fields `initialActors`, `runtimeOutputActors`
- `internal/router/router_test.go:567-568` — test struct field `inputActors`
- `internal/router/router_test.go:2344-2347` — CreateTask request struct
- `internal/router/router_on_error_test.go:22-23` — `expectedActors`, `expectedCurrent`

All test message fixtures must use `{"prev": [...], "curr": "...", "next": [...]}`.

## Test plan

- All existing sidecar unit tests pass with new format
- Route methods return correct values for empty/single/multi-actor routes
- `IncrementCurrent()` on last actor (`Next` empty) handled gracefully
- Error payload extraction works with new format

## References

- RFC: 1iah/rfc.md section 3.1
