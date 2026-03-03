---
title: Support match statement as conditional routing
priority: 3 # low
---

Add `ast.Match` (Python 3.10+) handling as an alternative to if/elif chains
for conditional routing:

```python
match state["order_type"]:
    case "express":
        state = express_handler(state)
    case "standard":
        state = standard_handler(state)
    case _:
        state = fallback_handler(state)
```

Compiles to the same `Condition` IR nodes as if/elif — each `case` becomes a
branch. Only literal value patterns and wildcard `_` supported initially;
structural patterns (destructuring, guards) can be added later.

**Requires**: Python 3.10+ in the compiler environment.

**Files**: `parser.py` (add `_parse_match()`), `test_parser.py`.
