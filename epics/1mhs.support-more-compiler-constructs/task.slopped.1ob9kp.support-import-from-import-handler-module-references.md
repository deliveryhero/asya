---
title: Support import/from-import for handler module references
priority: 3 # low
type: task
---

Allow `import` and `from ... import` at the top of flow files so users can
reference handler modules explicitly:

```python
from my_handlers import validate_order, process_payment

def order_flow(state: dict) -> dict:
    state = validate_order(state)
    state = process_payment(state)
    return state
```

Parser should accept `ast.Import` / `ast.ImportFrom` only at module level
(before the flow function definition). Imports inside the flow body remain
a compile error.

The imported names feed into actor name resolution during grouping.

**Files**: `parser.py` (module-level import handling), `test_parser.py`.
