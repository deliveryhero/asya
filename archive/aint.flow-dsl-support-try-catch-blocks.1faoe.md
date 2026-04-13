---
title: "Flow DSL: Support try-catch blocks"
status: merged
priority: 2
parent: 00000
tags:
  - type:feature
---

Extend Flow DSL compiler to support exception handling.

- Parse try/except/finally AST nodes
- Integrate with error-end routing for caught exceptions
- Generate router code for exception handling paths
- Consider retry semantics and error propagation

## Target Syntax

```python
def resilient_processing(p: dict) -> dict:
    try:
        p = risky_operation(p)
    except ContextWindowExceededError:
        # Graceful degradation
        p = truncate_context(p)
        p = risky_operation(p)
    except ValidationError as e:
        p["error"] = str(e)
        p["status"] = "failed"
        return p
    
    return p

def with_cleanup(p: dict) -> dict:
    try:
        p = acquire_resource(p)
        p = process_with_resource(p)
    finally:
        p = release_resource(p)
    
    return p
```

## Reference
Based on DSPy ReAct error handling: https://github.com/stanfordnlp/dspy/blob/631085c/dspy/predict/react.py#L121-L144


---
**Close reason**: Implemented in PR #185. Full try-except-finally support across compiler pipeline (parser, grouper, codegen, dotgen) and sidecar _on_error routing. 64 new tests, 4 example flows.


---
_Migrated from beads `asya-ync`_
