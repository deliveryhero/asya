---
title: Tool-Style Handler Signatures Research
status: open
priority: 3 # low
type: task
---

Research and design tool-style handler signatures for Asya actors.

## Problem
Current handlers require dict-based signatures:
```python
def process(p: dict) -> dict:
    return {"result": p["input"] * 2}
```

Agentic frameworks use typed signatures:
```python
@tool
def get_weather(location: str) -> str:
    return fetch_weather(location)
```

## Goal
Find simplest interface that:
1. Is easy to learn and develop
2. Allows mechanical translation from ADK/DSPy/LangGraph/etc to Asya
3. Maintains pure Python (no Asya-specific imports)
4. Flows remain runnable as regular Python functions

## Research Areas
1. Framework survey: ADK, LangChain, DSPy, LangGraph, AutoGen, CrewAI
2. AST analysis feasibility for flow structure inference
3. Runtime introspection for typed signatures
4. Compatibility layer for @tool decorators

## Constraints
- Pure Python (no asya pip package)
- No external config files (YAML/JSON)
- Must work with fan-out slicing

## References
- RFC: docs/rfc/asya-handler-signatures.md
- Related: docs/rfc/asya-fan-in-fan-out.md


---
_Migrated from beads `asya-vbc`_
