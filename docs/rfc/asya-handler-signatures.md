# RFC: Tool-Style Handler Signatures

**Status**: Research Required
**Author**: Architecture Discussion
**Date**: 2026-01-28
**Related**: asya-bi8-agentic-asya.md

---

## Problem Statement

Asya currently requires handlers to use dict-based signatures:

```python
def process(p: dict) -> dict:
    return {"result": p["input"] * 2}
```

Agentic frameworks (ADK, LangChain, DSPy, LangGraph) use typed signatures:

```python
@tool
def get_weather(location: str) -> str:
    """Get weather for a location."""
    return fetch_weather(location)
```

**Goal**: Find the simplest interface that:
1. Is easy to learn and develop
2. Allows mechanical/trivial translation from ADK/DSPy/LangGraph/etc to Asya
3. Maintains pure Python (no Asya-specific imports required)
4. Flows are runnable as regular Python functions

---

## Constraints

1. **Pure Python**: No `asya` pip package imports in handler code
2. **No external config**: No YAML/JSON schema files for mapping
3. **Runnable flows**: Flow functions must execute as regular Python
4. **Framework detection**: Support existing framework decorators (@tool, etc.)

---

## Current State

### Asya Handler Modes

From `asya_runtime.py`:

- **Payload mode**: `def handler(p: dict) -> dict` - receives/returns payload only
- **Envelope mode**: `def handler(e: dict) -> dict` - receives/returns full envelope

Both require dict signatures. No typed parameter support.

### Framework Signatures

**ADK @tool**:
```python
from google.adk.tools import tool

@tool
def get_weather(location: str, units: str = "celsius") -> str:
    """Get current weather for a location."""
    return f"Weather in {location}: 72{units}"
```
- Decorator provides metadata (name, description)
- Type hints define parameter schema
- Docstring used for LLM context

**LangChain @tool**:
```python
from langchain_core.tools import tool

@tool
def search(query: str) -> str:
    """Search the web."""
    return web_search(query)
```

**DSPy Signatures**:
```python
class RAG(dspy.Module):
    def forward(self, question: str) -> str:
        context = self.retrieve(question)
        return self.generate(context, question)
```

---

## Explored Approaches

### Approach 1: Flow Structure Inference

The flow structure itself reveals input/output mapping:

```python
def my_flow(p: dict) -> dict:
    p["weather"] = get_weather(p["location"])
    return p
```

Compiler infers from AST:
- **Input**: `p["location"]` → extract `location` field
- **Output**: `p["weather"]` → place result in `weather` field
- **Handler**: `get_weather` → deploy as actor

**Pros**:
- No decorator needed
- Pure Python
- Mapping explicit in code

**Cons**:
- Complex AST analysis
- Doesn't work for standalone actors (not in flow)

### Approach 2: Framework Decorator Detection

Detect existing framework decorators:

```python
@tool  # ADK or LangChain decorator
def get_weather(location: str) -> str:
    return fetch_weather(location)
```

Runtime detects `@tool` and uses its introspection:
- ADK: `func.__wrapped__`, parameter schemas
- LangChain: `func.args_schema`

**Pros**:
- Zero migration effort for existing code
- Frameworks already solved the schema problem

**Cons**:
- Framework dependency for decorator
- Different frameworks have different metadata

### Approach 3: Type Hint Introspection

Use standard Python type hints:

```python
def get_weather(location: str, units: str = "celsius") -> str:
    return fetch_weather(location)
```

Runtime uses `inspect.signature()` to extract:
- Parameter names and types
- Default values
- Return type

**Pros**:
- Pure Python (no imports)
- Standard typing

**Cons**:
- Doesn't specify which payload field maps to which param
- Return value placement unclear

### Approach 4: Detection Hierarchy

Combine approaches with priority:

1. If `@tool` decorator present → use framework's schema
2. If typed signature → introspect and match payload fields by name
3. If `dict -> dict` → pass payload as-is (current behavior)

**Open question**: How to handle field name mismatches?
```python
# Payload has: {"loc": "NYC"}
# Handler expects: location: str
# How does runtime know loc → location?
```

---

## Fan-Out Slice Context

In fan-out scenarios, sub-agents receive minimal payload (just their slice):

```python
# Flow:
p["results"] = [analyze(p["items"][i]) for i in range(len(p["items"]))]

# Slice payload arriving at analyze actor:
{"id": 1, "text": "hello"}

# Handler:
def analyze(text: str) -> dict:
    return {"sentiment": classify(text)}
```

The flow compiler knows:
- Input: `p["items"][i]` (each element)
- Each element has structure `{"id": ..., "text": ...}`
- Handler expects `text: str`

**Can compiler generate extraction code?**
```python
# Generated router code:
text = slice_payload["text"]
result = analyze(text)
output_payload = {"sentiment": result}  # or result if already dict
```

---

## Research Required

### 1. Framework Survey

Analyze signature patterns across:
- Google ADK
- LangChain / LangGraph
- DSPy
- AutoGen
- CrewAI
- Semantic Kernel

Questions:
- How does each define tool/agent signatures?
- What metadata is available (descriptions, schemas)?
- How do they handle streaming (yield)?

### 2. AST Analysis Feasibility

For flow-structure inference:
- Can we reliably extract field mappings from expressions like `get_weather(p["location"])`?
- How to handle complex expressions: `get_weather(p["data"]["location"].strip())`?
- Edge cases: dynamic keys, computed values

### 3. Runtime Introspection

For typed signatures:
- Performance cost of `inspect.signature()` per call vs. cached
- Handling of `*args`, `**kwargs`
- Union types, Optional, generics

### 4. Backward Compatibility

- How to migrate existing `dict -> dict` handlers?
- Can both styles coexist?
- Deprecation path

---

## Open Questions

1. **Field name mapping**: How to handle payload field names that don't match parameter names?

2. **Output placement**: For `def f(x: str) -> str`, which payload field receives the result?

3. **Streaming compatibility**: How do typed signatures work with async generators?
   ```python
   async def agent(task: str) -> str:  # But also yields events?
       yield {"partial": True, "text": "thinking..."}
       return "final answer"
   ```

4. **Nested objects**: How to handle complex input types?
   ```python
   def process(user: User) -> Result:  # User is a dataclass/Pydantic model
       ...
   ```

5. **Validation**: Should Asya validate types at runtime? Performance impact?

---

## Next Steps

1. Survey 5-6 major agentic frameworks for signature patterns
2. Prototype AST-based flow inference
3. Prototype runtime introspection for typed handlers
4. Design compatibility layer for @tool decorators
5. Write detailed RFC with chosen approach

---

## References

- [ADK Tools Documentation](https://google.github.io/adk-docs/tools/)
- [LangChain Tools](https://python.langchain.com/docs/modules/tools/)
- [DSPy Signatures](https://dspy-docs.vercel.app/)
- [Python inspect module](https://docs.python.org/3/library/inspect.html)
- [PEP 484 - Type Hints](https://peps.python.org/pep-0484/)
