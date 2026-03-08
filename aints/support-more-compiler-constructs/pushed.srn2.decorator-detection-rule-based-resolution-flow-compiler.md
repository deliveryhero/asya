---
title: Decorator detection and rule-based resolution in flow compiler
priority: 2 # medium
tags:
  - pr:280
---


## Problem

The flow compiler ignores all decorators on function definitions. It does not
inspect `func.decorator_list` (parser.py:90-103). This blocks the compiler rules
system from recognizing `@actor`, `@flow`, `@retry`, and other decorators.

Supersedes/refines [n67c] (strip handler decorators) with a concrete
implementation design based on the compiler rules system in
`.aint/aints/asya-lab/research-compiler-knowledge-base.md`.

## Design

When the compiler resolves a function call `p = handler(p)`, it should also
check the function definition's decorator list. Each decorator is matched
against compiler rules independently:

- `treat-as: actor` — marks the function as an actor boundary
- `treat-as: flow` — marks as a sub-flow entry point
- `treat-as: config` — strip decorator, extract args into env vars
- No matching rule — keep decorator at runtime (default)

Multiple decorators compose independently:
```python
@actor                    # → treat-as: actor (call resolution)
@retry(stop=stop_after_attempt(3))  # → treat-as: config (strip + extract)
async def llm_call(state: dict) -> dict:
    ...
```

### Implementation

**Parser** (`src/asya-cli/asya_cli/flow/parser.py`):

The parser currently resolves function calls in `_parse_actor_call()` (line 217).
To detect decorators, the compiler needs access to the function definition, not
just the call site. This requires the "dive into functions" mechanism from [1mhs]:

1. When encountering `p = handler(p)`, resolve `handler` to its definition
2. Import the module containing `handler` (already needed for decompose)
3. Read `func.decorator_list` from the definition's AST
4. For each decorator, resolve its name and match against compiler rules
5. Apply the most specific matching rule

For decorators with `treat-as: config`:
1. Extract decorator arguments from AST
2. Import the decorator class/function at compile time
3. Use `inspect.signature` to bind positional args to param names
4. Map param names to env vars via `extract` config
5. Store extracted config alongside the ActorCall IR node

**IR** (`src/asya-cli/asya_cli/flow/ir.py`):

Extend `ActorCall`:
```python
@dataclass
class ActorCall(IROperation):
    name: str
    extracted_config: dict[str, str] | None = None  # env_var → value
```

**Grouper/Codegen**:
- Pass through `extracted_config` to generated actor metadata
- When generating CRD manifests (future), inject as env vars

### Dependency

This depends on the compiler having access to function definitions, which
requires either:
- (a) The function is in the same file/package (parser can read the AST)
- (b) The function is importable at compile time (parser can `import` and
  `inspect.getsource`)

Both paths are needed for the full rules system.

### Testing

- Unit: function with `@actor` decorator → treat-as-actor
- Unit: function with `@retry(...)` → strip + extract config
- Unit: function with multiple decorators → independent resolution
- Unit: function with unknown decorator → keep (default)
- Unit: config extraction from tenacity `@retry` with positional args
- Unit: config extraction from stamina `@retry` with kwargs
- Integration: full flow with mixed decorators compiles correctly

See `.aint/aints/asya-lab/research-compiler-knowledge-base.md` for extraction
design and tenacity signature research.
