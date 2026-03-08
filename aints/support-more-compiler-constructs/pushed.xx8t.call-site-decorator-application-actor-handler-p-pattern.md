---
title: "Call-site decorator application: actor(handler)(p) pattern"
priority: 2 # medium
tags:
  - pr:280
---


## Problem

The flow compiler rejects nested `ast.Call` nodes. When the parser sees
`p = actor(handler)(p)`, it cannot extract the function name because
`call.func` is itself a `Call` node, not a `Name` or `Attribute`
(parser.py:225-245).

This blocks the call-site decorator pattern where users apply `actor()`,
`inline()`, or other markers at the call site instead of on the function
definition.

## Design

Call-site decorator application is semantically equivalent to definition-site
decorators:

```python
# These are equivalent:
p = actor(handler)(p)        # call-site application

@actor                       # definition-site decorator
def handler(p): ...
p = handler(p)
```

The compiler recognizes `actor` from the same rules as decorator detection.
No separate "wrapper" concept — Python's decorator and call-site application
are the same mechanism.

### Supported patterns

```python
p = actor(handler)(p)        # treat handler as actor
p = inline(uuid4)(p)         # treat uuid4 as inline (mutation)
p = flow(sub_pipeline)(p)    # treat sub_pipeline as sub-flow
```

The outer function name (`actor`, `inline`, `flow`) is looked up in compiler
rules. The inner function name (`handler`, `uuid4`, `sub_pipeline`) is the
actual symbol being classified.

### Implementation

**Parser** (`src/asya-cli/asya_cli/flow/parser.py`):

In `_parse_actor_call()` (line 217), extend `call.func` handling:

```python
def _parse_actor_call(self, stmt: ast.Assign) -> ActorCall:
    call = stmt.value
    if isinstance(call, ast.Await):
        call = call.value

    # Handle call-site decorator: actor(handler)(p)
    if isinstance(call.func, ast.Call):
        outer_call = call.func
        # Extract outer function name (e.g., "actor")
        if isinstance(outer_call.func, ast.Name):
            wrapper_name = outer_call.func.id
        elif isinstance(outer_call.func, ast.Attribute):
            wrapper_name = ast.unparse(outer_call.func)
        else:
            raise FlowCompileError(...)

        # Extract inner function name from outer call's argument
        if len(outer_call.args) != 1:
            raise FlowCompileError(...)
        inner_arg = outer_call.args[0]
        if isinstance(inner_arg, ast.Name):
            actor_name = inner_arg.id
        elif isinstance(inner_arg, ast.Attribute):
            actor_name = ast.unparse(inner_arg)
        else:
            raise FlowCompileError(...)

        # Look up wrapper_name in compiler rules to determine treat-as
        return ActorCall(
            lineno=stmt.lineno,
            name=actor_name,
            call_site_marker=wrapper_name,
        )

    # ... existing Name/Attribute handling ...
```

**IR** (`src/asya-cli/asya_cli/flow/ir.py`):

Extend `ActorCall`:
```python
@dataclass
class ActorCall(IROperation):
    name: str
    call_site_marker: str | None = None  # e.g., "actor", "inline"
```

**Grouper**: When `call_site_marker` is present, use it to determine the
operation type (actor boundary vs inline mutation vs flow).

### Validation

- `actor(handler)(p)` — outer must have exactly 1 argument (the inner function)
- Inner argument must be a `Name` or `Attribute` (not another Call)
- Outer function name must match a compiler rule
- The actual call `(p)` must still have exactly 1 argument

### Testing

- Unit: `p = actor(handler)(p)` → ActorCall with name="handler"
- Unit: `p = inline(uuid4)(p)` → Mutation (or ActorCall with inline marker)
- Unit: `p = await actor(handler)(p)` → unwrap Await, then handle nested Call
- Unit: `p = unknown_wrapper(handler)(p)` → error (no matching rule)
- Unit: `p = actor(module.handler)(p)` → ActorCall with name="module.handler"

See `.aint/aints/asya-lab/research-compiler-knowledge-base.md` for the
full rules system design.
