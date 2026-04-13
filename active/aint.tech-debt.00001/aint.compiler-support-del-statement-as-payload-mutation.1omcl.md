---
title: Support del statement as payload mutation
status: open
priority: 3
parent: 00001
---

Add `ast.Delete` handling in `parser.py:_parse_statement()`. Only `del p["key"]`
and `del p["a"]["b"]` forms are valid — anything else is a compile error.

Compiles to a `Mutation` IR node with `code = "del p[\"key\"]"` (unparsed).

```python
# Flow code
del state["temp"]

# Generated router code (after normalization)
del p["temp"]
```

**Files**: `parser.py` (add case), `test_parser.py` (add tests).
