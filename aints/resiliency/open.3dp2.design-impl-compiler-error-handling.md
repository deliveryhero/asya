---
title: "design+impl: Compiler error handling"
priority: 2 # medium
---

## Context

The flow compiler currently translates a `try/except` block into **4 routers**:

- `try_enter` — sets `headers._on_error = except_dispatch_router`, inserts try body
- `try_exit` — clears `_on_error` on success, appends finally + continuation
- `except_dispatch` — reads `status.error.type/mro`, matches handler by type, routes to handler + finally + continuation
- `reraise` — raises `RuntimeError` for unhandled error types (when no bare `except:`)

Problems:
- 4 routers per try block, multiplying graph complexity
- `_on_error` is a hidden side-channel header threaded through every envelope inside a try scope; it requires the sidecar's `routeToFlowErrorHandler` to intercept errors and reroute
- Error-type dispatch in Python (router reads `status.error`) instead of at the sidecar level (`retryRules`)
- Visualization is noisy — 4 intermediate nodes per try block
- `try_exit` exists solely to clear `_on_error` on success — it does nothing useful except coordinate header state

## Proposed design

### Core idea

Replace all 4 special router types with:
- **N except_routers** (one per except clause) — each statically overwrites `route.next` with its handler's continuation path
- **Actor manifest retryRules** — the sidecar dispatches to the correct except_router based on error type; no Python-level type dispatch needed
- **Natural finally insertion** — finally actors are appended to the try body route on success; no `try_exit` needed
- **No `_on_error` header** — error routing is expressed declaratively in actor manifests

### Trace

```python
try:
    p = validate_order(p)
    p = process_order(p)
except ValueError:
    p = notify_rejection(p)
p = final_step(p)
```

**routers.py** — one router generated:

```python
def try_except_router_my_flow_line_3(p):
    yield "SET", ".route.next", ["notify_rejection", "final_step", "end_my_flow"]
    yield p
```

**validate_order and process_order manifests** — resiliency block prepended:

```yaml
resiliency:
  policies:
    try_except_line_3_ve:
      maxAttempts: 1
      thenRoute: ["try-except-router-my-flow-line-3"]
  retryRules:
    - errors: ["ValueError"]
      policy: try_except_line_3_ve
```

Error in `validate_order`:
- `route.next` at time of error = `[process_order, final_step, end]`
- sidecar `retryRules` → `try_except_line_3_ve` → routes to `try_except_router_my_flow_line_3`
- router overwrites `route.next = [notify_rejection, final_step, end]`
- `process_order` skipped ✅, `notify_rejection` runs, then `final_step` ✅

Error in `process_order`:
- `route.next` at time of error = `[final_step, end]`
- same sidecar dispatch → same router → same overwrite
- `notify_rejection` runs, then `final_step` ✅

The router doesn't care what `route.next` contained — it always overwrites with the statically-known correct path.

### Multiple except clauses

One except_router per handler; each actor in the try body gets all matching retryRules:

```python
try:
    p = actor_a(p)
except ValueError:
    p = notify_rejection(p)
except TypeError:
    p = type_error_handler(p)
p = final_step(p)
```

Generates two routers: `except_router_ve` and `except_router_te`.

`actor_a` manifest gets both retryRules prepended (in handler declaration order):

```yaml
resiliency:
  policies:
    try_except_line_3_ve: {maxAttempts: 1, thenRoute: ["except-router-ve"]}
    try_except_line_3_te: {maxAttempts: 1, thenRoute: ["except-router-te"]}
  retryRules:
    - errors: ["ValueError"]
      policy: try_except_line_3_ve
    - errors: ["TypeError"]
      policy: try_except_line_3_te
```

### finally blocks

On **success**: finally actors are inserted into the route naturally — the compiler
appends `finally_actors` after the last try-body actor's position in the route, before
continuation. No `try_exit` router needed.

On **error**: each except_router includes `finally_actors` in its static `route.next`.

```python
try:
    p = actor_a(p)
except ValueError:
    p = handler(p)
finally:
    p = cleanup(p)
p = final_step(p)
```

Success route: `[actor_a, cleanup, final_step]`
except_router routes to: `[handler, cleanup, final_step]`

### raise in except body

The except_router routes to `["x-sink"]`. The flow terminates (payload is persisted
by x-sink, error details remain in `status.error`).

### bare except

A bare `except:` is a catch-all: the compiler sets `policies.default.thenRoute` on the
actor manifest to point to the bare-except router. No `retryRules` entry needed — the
default fires when no other rule matches. If the actor already has `policies.default`
defined in its own spec, this is a compile error (cannot have bare `except:` on an
actor with an existing default policy).

### retryRules priority

Compiler-generated retryRules are **prepended** before any existing actor retryRules
in the stamped manifest. This ensures flow-level `try/except` semantics take precedence
for matched error types. An actor's own `policies.default` (e.g., `maxAttempts: 5`)
continues to apply for error types not covered by the `try/except` block.

See `[7179]` §retryRules evaluation order for the full first-match semantics.

## Implementation plan

### 1. Grouper: replace 4-router pattern with 1-router-per-handler

`src/asya-lab/asya_lab/flow/grouper.py`:

Add `ActorRetryRule` dataclass:
```python
@dataclass
class ActorRetryRule:
    error_types: list[str] | None  # None = bare except → policies.default
    policy_name: str               # e.g. "try_except_line_3_ve"
    then_route: list[str]          # K8s actor names for thenRoute
```

Add `actor_retry_rules: dict[str, list[ActorRetryRule]]` to `OperationGrouper`
(populated by `_process_try_except`; merged across nested try blocks).

Remove from `Router` dataclass:
- `is_try_enter`, `is_try_exit`, `is_reraise`
- `except_dispatch_name`, `reraise_name`
- rename `is_except_dispatch` → `is_except_router`

Rewrite `_process_try_except(try_except, continuation)`:
- For each handler: create one `except_router` with
  `true_branch_actors = [handler_actors, finally_actors, continuation]`
- For bare `except:` handler: set `is_except_router=True` and mark as default (no retryRules, uses policies.default)
- Record `ActorRetryRule` for every try-body actor (prepend per actor)
- Return `[body_actors, finally_actors, continuation]` as the normal success route

### 2. CodeGenerator: remove 3 router generators

`src/asya-lab/asya_lab/flow/codegen.py`:

Remove:
- `_generate_try_enter_router`
- `_generate_try_exit_router`
- `_generate_reraise_router`
- corresponding branches in `_generate_routers`

Simplify `_generate_except_dispatch_router` → `_generate_except_router`:
- No reading of `status.error.*` — just overwrites `route.next` with static list
- Body: `yield "SET", ".route.next", [<handler>, <finally...>, <continuation...>]` then `yield p`
- For `raise` variant: `yield "SET", ".route.next", ["x-sink"]` then `yield p`

Update `_is_single_actor_flow`: remove `is_try_enter` guard (no longer exists).

### 3. FlowCompiler: thread retry rules to templater

`src/asya-lab/asya_lab/flow/compiler.py`:

After `_group()`, extract `grouper.actor_retry_rules` and store on `self`.
Pass to `ManifestTemplater` as `actor_retry_rules` kwarg.

### 4. ManifestTemplater: inject resiliency into actor manifests

`src/asya-lab/asya_lab/compiler/templater.py`:

Accept `actor_retry_rules: dict[str, list[ActorRetryRule]]` in `__init__`.

In `_stamp_actor(path, actor)` for non-router actors:
- Look up `actor_retry_rules.get(actor_name, [])`
- If non-empty: merge `spec.resiliency.policies` (add generated policies) and
  prepend entries to `spec.resiliency.retryRules`
- For bare-except actor (no `error_types`): set `spec.resiliency.policies.default.thenRoute`
  if not already set; error if already set

K8s name conversion: `then_route` values in `ActorRetryRule` are stored as Python
names; convert to K8s names (hyphens) at stamping time.

### 5. Sidecar: remove _on_error header mechanism

`src/asya-sidecar/internal/router/router.go`:

- Remove `routeToFlowErrorHandler` function
- Remove `_on_error` header check from `handleErrorResponse` (lines ~281-283)
- The `retryRules` dispatch from `[7179]` handles what `_on_error` used to do

**Note**: step 5 must land together with or after `[7179]` sidecar implementation.
Until `[7179]` lands, the `_on_error` mechanism in the sidecar must remain in place
(backward compat with flows compiled with the old compiler).

### 6. DotGenerator: clean up try visualization

`src/asya-lab/asya_lab/flow/dotgen.py`:

Remove special-case handling for `is_try_enter`, `is_try_exit`, `is_reraise` nodes.
`is_except_router` nodes render as regular routers. Error-type edges (for visualization)
are derived from `actor_retry_rules` — draw a labeled edge from each try-body actor
to its except_router annotated with the error type(s).

### 7. Tests

Remove or rewrite:
- `tests/flow/test_try_except_grouper.py` — update to assert N routers not 4-router pattern
- `tests/flow/test_try_except_codegen.py` — update expected generated code
- `tests/flow/test_try_except_integration.py` — update end-to-end flow tests

Add:
- `tests/compiler/test_try_except_manifest.py` — assert correct `retryRules` and
  `policies` injection into actor manifests for single handler, multiple handlers,
  finally, raise, bare except, actor-with-existing-retry interaction

## Acceptance criteria

- [ ] `_process_try_except` produces N routers (one per handler) + `actor_retry_rules`, not 4 special routers
- [ ] No `is_try_enter`, `is_try_exit`, `is_reraise` flags remain in `Router` or codegen
- [ ] Compiler stamps `spec.resiliency.policies` + `spec.resiliency.retryRules` into try-body actor manifests
- [ ] Compiler-generated retryRules prepend before actor's own rules in the manifest
- [ ] `finally` actors appear on both success route and all except_router routes; no `try_exit` router exists
- [ ] `raise` in except body: except_router routes to `["x-sink"]`
- [ ] bare `except:`: `policies.default.thenRoute` set; compile error if actor already has `policies.default`
- [ ] `_on_error` header check removed from sidecar `handleErrorResponse`
- [ ] `routeToFlowErrorHandler` removed from sidecar
- [ ] Unit tests: single handler, multiple handlers, finally, raise, bare except
- [ ] Unit test: actor with existing `@retry` — generated rules prepend, default still active for unmatched types
- [ ] Integration test: error routing matches expected flow semantics end-to-end
- [ ] DotGenerator: no try_enter/try_exit/reraise nodes; error edges labeled with type

## Dependencies

- `[7179]` must land first: provides retryRules + thenRoute sidecar implementation
- `[nqf5]` must land first: `sendRetryFailure` routes through x-sink (not directly to x-sump)
- Sidecar step (§5) must ship atomically with `[7179]` sidecar — do not remove `_on_error`
  handling until retryRules dispatch is live

## Comparison with current approach

| | Current (4 routers) | Proposed (N routers + errorRoutes) |
|---|---|---|
| Router count per try | 4 (enter, exit, dispatch, reraise) | N (one per except clause) |
| Error signaling | `_on_error` header threaded through envelope | `retryRules` in actor manifest (static) |
| Type dispatch | Python code in except_dispatch router | Sidecar retryRules first-match |
| finally on success | Handled by try_exit router | Natural route insertion |
| Visualization | 4 intermediate nodes | Direct error-type-labeled edges |
| Actor retry interaction | `_on_error` bypasses retry entirely | retryRules first-match; actor default still active for unmatched types |
