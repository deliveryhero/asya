---
title: Allow arbitrary flow parameter name beyond p/payload/state
status: merged
priority: 1
parent: drsjr
reason: "Implemented: removed VALID_PARAM_NAMES whitelist, any param name accepted"
---

Remove the `VALID_PARAM_NAMES` whitelist in `parser.py`. Any single-parameter
name should work (`ctx`, `data`, `msg`, `x`, etc.). The `_ParamNormalizer`
already normalizes to canonical `p` internally — just remove the gate.

```python
# All of these should be valid:
def flow(ctx: dict) -> dict: ...
def flow(data: dict) -> dict: ...
def flow(msg: dict) -> dict: ...
```

**Validation**: still require exactly one positional parameter with a `dict`
return annotation. Just don't restrict the parameter name.

**Files**: `parser.py` (remove `VALID_PARAM_NAMES` check at line ~100),
`test_parser.py` (update/add tests).
