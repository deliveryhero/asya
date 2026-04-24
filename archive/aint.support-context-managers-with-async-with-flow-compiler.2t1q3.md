---
title: Support context managers (with/async with) in flow compiler
status: merged
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - pr:281
reason: "PR #281 merged"
---


## Problem

The flow compiler rejects `ast.With` and `ast.AsyncWith` statements with
`Unsupported statement type: With` (parser.py:143). Context managers like
`asyncio.timeout()` and custom context managers cannot be used in flow
definitions.

## Design

Context managers should be matched by the compiler rules system described in
`research-compiler-knowledge-base.md` (`.aint/aints/asya-lab/`). The `treat-as`
classification determines what the compiler does:

- `treat-as: config` — strip the context manager, extract args into env vars,
  compile body normally. Example: `async with asyncio.timeout(30):`
- `treat-as: inline` — keep the context manager in generated router code,
  compile body normally. Example: custom resource managers.
- No matching rule — compiler error (unrecognized context manager).

### Example

```python
async def my_flow(p: dict) -> dict:
    async with asyncio.timeout(30):    # matched by rule, stripped, timeout extracted
        p = slow_handler(p)
        p = another_handler(p)
    return p
```

With compiler rule:
```yaml
- module: "asyncio.timeout"
  treat-as: config
  extract:
    asyncio.timeout:
      delay: ASYA_RESILIENCY_ACTOR_TIMEOUT
```

The compiler strips the `async with` wrapper, extracts `30` as actor timeout,
and compiles the body actors normally. Each actor in the scope gets the extracted
config applied.

### Implementation

**Parser** (`src/asya-cli/asya_cli/flow/parser.py`):

Add handler in `_parse_statement()` at line ~140:
```python
elif isinstance(stmt, ast.With | ast.AsyncWith):
    return self._parse_with(stmt)
```

`_parse_with()` should:
1. Extract context manager expression (the `ast.withitem.context_expr`)
2. Resolve to a symbol name (e.g., `asyncio.timeout`)
3. Look up in compiler rules
4. If `treat-as: config`: parse body, return body ops + config extraction metadata
5. If `treat-as: inline`: wrap body in a ContextManager IR node
6. If no rule: raise FlowCompileError

**IR** (`src/asya-cli/asya_cli/flow/ir.py`):

For `treat-as: inline`, add:
```python
@dataclass
class WithBlock(IROperation):
    expr: str                      # e.g., "asyncio.timeout(30)"
    is_async: bool
    body: list[IROperation]
```

For `treat-as: config`, no new IR needed — body ops are returned directly,
config extraction is handled separately.

**Grouper** (`src/asya-cli/asya_cli/flow/grouper.py`):
- Handle `WithBlock` by processing body operations, wrapping generated code
  in the context manager expression.

**Codegen** (`src/asya-cli/asya_cli/flow/codegen.py`):
- Generate `async with expr:` / `with expr:` blocks around body code for
  inline context managers.

### Extraction mechanism

Uses runtime `inspect.signature` at compile time (same as decorator extraction):
1. Import `asyncio.timeout`
2. Bind positional args using signature
3. Map param names to env vars via `extract` config

See `.aint/aints/asya-lab/research-compiler-knowledge-base.md` for full
extraction design.

### Testing

- Unit: parse `async with asyncio.timeout(30): p = handler(p)` with config rule
- Unit: parse `with custom_ctx(): p = handler(p)` with inline rule
- Unit: reject unknown context manager (no rule)
- Unit: nested context managers
- Unit: context manager with multiple `withitem`s (`with a() as x, b() as y:`)

## Known limitation

This PR implements **per-actor** config application (each actor in the scope
gets the config independently). The correct semantics is **per-scope** (e.g.,
`asyncio.timeout(30)` should be a pipeline-level deadline, not per-actor
timeout). Per-scope semantics is tracked in [ia37].

## References

- `.aint/aints/asya-lab/research-compiler-knowledge-base.md` — extraction
  design, `inspect.signature` at compile time
- `.aint/aints/asya-lab/rfc.md` §9.1 — compiler rules summary
- Aint [ia37] — per-scope semantics (follow-up to this PR)
