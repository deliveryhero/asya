---
title: Allow compiler to dive into functions
priority: 2 # medium
type: task
---




Teach the flow compiler to resolve function calls and decide whether to
**dive in** (decompose/inline) or **treat as opaque** (actor boundary).

## Resolution logic

When the compiler encounters `p = handler(p)`, it resolves the call using this
priority chain:

| Priority | Signal | Effect |
|---|---|---|
| 1 | Inline comment `# asya: actor` | Opaque actor (don't inline) |
| 2 | Inline comment `# asya: flow` | Sub-flow (compile recursively) |
| 3 | Inline comment `# asya: inline` | Force inline into router code |
| 4 | Call-site wrapper `actor(handler)(p)` | Opaque actor |
| 5 | `@actor` decorator on definition | Opaque actor |
| 6 | `@flow` decorator on definition | Flow entry point |
| 7 | Function defined in **user code** (same file / same package dir) | **Dive in** (decompose) |
| 8 | Function defined in **external package** (stdlib, pip) | Treat as mutation (inline the call as-is) |
| 9 | Cannot import / resolve | **Compiler error** |

**Default = dive in** for user code, **mutation** for external code. No silent
"assume actor" — every call must be resolvable.

## Decorator mechanism

Users define their own `@actor` decorator. The compiler detects it by name
(configurable in `asya.yaml`), not by import path. No asya-lab dependency
needed in handler packages.

```python
# Real decorator: wraps ABI generator into a coroutine for local testing.
# At deploy time, sidecar calls the bare function via __wrapped__.
def actor(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        gen = func(*args, **kwargs)
        events = [e async for e in gen if not isinstance(e, tuple)]
        if len(events) != 1:
            raise ValueError(f"Expected 1 yield, got {len(events)}")
        return events[0]
    return wrapper
```

Detection: compiler imports the function, then walks the `__wrapped__` chain
checking `__name__` against configured decorator names.

```python
def has_decorator(func, decorator_name):
    if func.__name__ == decorator_name:
        return True
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__
        if func.__name__ == decorator_name:
            return True
    return False
```

### Configurable names

```yaml
# asya.yaml
compiler:
  decorators:
    actor: [actor]        # decorator names that mark opaque actors
    flow: [flow]          # decorator names that mark flow entry points
```

## Call-site wrapper (inline application)

The `actor()` decorator can also be applied at the call site for functions from
external packages that can't have `@actor` at their definition:

```python
async def my_flow(state: dict) -> dict:
    # actor(llm) returns a coroutine wrapper; (state) calls it
    state = await actor(llm)(state)
    state = await actor(validator)(state)
    return state
```

This works both at runtime (generator to coroutine conversion) and at compile
time (compiler sees `actor(...)` wrapper pattern and treats inner function as
opaque actor).

## Inline comments (mypy-style overrides)

Override resolution for a specific call site:

```python
async def my_flow(state: dict) -> dict:
    state = sql_specialist(state)      # asya: actor   -- don't inline
    state = helper_transform(state)    # asya: inline  -- force inline
    state = sub_pipeline(state)        # asya: flow    -- compile recursively
    return state
```

## User code vs external code detection

The compiler determines whether a function is "user code" by checking if
its source file is within the same directory tree as the flow file being
compiled. Specifically:

- **User code**: function's `inspect.getfile(func)` is in the same package
  or a sibling package under the project root
- **External code**: function comes from site-packages, stdlib, or outside
  the project root

User code functions are **dived into** (their source is parsed and
decomposed into router operations). External code functions (like
`uuid.uuid4()`, `json.dumps()`) are treated as **mutations** — the call
is inlined as-is into the generated router code.

## Example: full flow with mixed resolution

```python
import functools
import uuid
from external_ml_lib import predict

# User-defined decorator (real runtime wrapper)
def actor(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        gen = func(*args, **kwargs)
        events = [e async for e in gen if not isinstance(e, tuple)]
        if len(events) != 1:
            raise ValueError(f"Expected 1 yield, got {len(events)}")
        return events[0]
    return wrapper

# Actor: has @actor, uses ABI yields, deployed as separate actor
@actor
async def llm(state):
    yield "FLY", {"type": "text_delta", "token": "hello"}
    yield "FLY", {"type": "text_delta", "token": "world"}
    event = {"tool_call": 123}
    if "events" not in state:
        state["events"] = []
    state["events"].append(event)
    yield state

# User helper: no decorator, in same package -> compiler dives in
def enrich(state: dict) -> dict:
    if state.get("priority") == "high":
        state["fast_track"] = True
    state["enriched"] = True
    return state

# Flow entry point
@flow
async def my_pipeline(state: dict) -> dict:
    state["id"] = str(uuid.uuid4())            # external -> mutation
    state = enrich(state)                       # user code -> dive in
    state = await actor(llm)(state)             # call-site wrapper -> actor
    state = await actor(predict)(state)         # external + wrapper -> actor
    state = validator(state)  # asya: actor     # comment override -> actor
    return state
```

What the compiler produces:
- `uuid.uuid4()` and `json.dumps()` → inlined as code in the start router
- `enrich()` → decomposed: its `if` becomes a conditional router, mutations
  are batched
- `llm`, `predict`, `validator` → opaque actor calls via `resolve()`

## Future: more decorators

Later we may explore additional decorators recognized by the compiler:
- `@retry` / tenacity's `@retry` → generate `ASYA_ERROR_*` retry config
- `@timeout` → generate timeout configuration
