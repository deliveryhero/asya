---
title: "Compiler rules: extend WhereNode with append-to and value for policies+rules XR fields"
priority: 2 # medium
tags:
  - integrate-into:gml9
  - absorbed-into:gml9
---



## Context

The flow compiler's `where:` extraction tree currently maps AST arguments to scalar XR spec paths via `assign-to:`. After the resiliency schema migration (policies+rules, PR #334), two patterns are needed that the current syntax cannot express:

1. **Literal constants** — the `policy: "default"` field in a rule entry is not extracted from the AST, it is a fixed string. There is no way to emit it today.
2. **List append** — `spec.resiliency.rules` is a list of dicts. The dot-path writer can set scalar fields but cannot push a whole dict entry onto a list.

## Proposed extension

Two new `WhereNode` fields in `src/asya-lab/asya_lab/compiler/rules.py`:

| Field | YAML key | Semantics |
|---|---|---|
| `value: object` | `value:` | Emit this literal as the extracted value (no AST param lookup) |
| `append_to: str` | `append-to:` | Group children's `assign-to` results into a single dict, append to the list at this path |

Inside an `append-to` node, `assign-to` values are relative keys within the entry dict, not global dot-paths.

### Example YAML rule (tenacity → policies+rules)

```yaml
- match: "tenacity.retry"
  where:
    - param: stop
      where:
        - param: max_attempt_number
          assign-to: spec.resiliency.policies.default.maxAttempts
        - param: max_delay
          assign-to: spec.resiliency.policies.default.maxDuration
    - param: wait
      where:
        - param: min
          assign-to: spec.resiliency.policies.default.initialDelay
        - param: max
          assign-to: spec.resiliency.policies.default.maxInterval
    - param: retry
      where:
        - match: retry_if_exception_type
          append-to: spec.resiliency.rules
          where:
            - param: exception_types
              assign-to: errors
            - value: "default"
              assign-to: policy
```

### Output shape

```python
{
    "spec.resiliency.policies.default.maxAttempts": 3,
    "spec.resiliency.rules": [
        {"errors": "ValueError", "policy": "default"}
    ],
}
```

## Files to change

- `src/asya-lab/asya_lab/compiler/rules.py` — add `value` and `append_to` to `WhereNode`, parse in `from_dict`
- `src/asya-lab/asya_lab/compiler/extractor.py` — handle `node.value` (literal) and `node.append_to` (list-push) in `_walk`
- `src/asya-lab/tests/test_extractor.py` — unit tests for both new node types
- `src/asya-lab/tests/test_rules_e2e.py` — update `_TENACITY_RULES_YAML` to use new paths and add `append-to` for the `retry` param

## Known follow-up gaps (not in scope)

- **Varargs**: `retry_if_exception_type(ValueError, KeyError)` — only index 0 is bound today; needs `collect-args: true`
- **Value mapping**: `multiplier=2` → `backoff: "exponential"`; needs a future `map:` node

## Dependency

Depends on PR #334 (resiliency policies+rules schema) being merged first.
