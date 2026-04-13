---
title: Support assert statement as compile-time flow guard
status: merged
priority: 1
parent: drsjr
reason: "Implemented: ast.Assert compiles to Mutation IR node"
---

Add `ast.Assert` handling in `parser.py:_parse_statement()`. Asserts compile to
a guard check in the generated router — if the condition fails, the router
raises and the sidecar routes to x-sump.

```python
# Flow code
assert state["valid"], "order validation failed"

# Generated router code
assert p["valid"], "order validation failed"
```

Compiles to a `Mutation` IR node with the unparsed assert statement.

**Files**: `parser.py` (add case), `test_parser.py` (add tests).
