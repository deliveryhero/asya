# DSPy Single Agent (ReAct Pattern)

Minimal example of a single agent using DSPy's ReAct pattern with tools.

## Setup

```bash
cd docs/comparisons/agentic_frameworks/dspy
uv sync
export OPENAI_API_KEY="sk-..."
```

## Run

```bash
uv run 01-single-agent/agent.py
```

## Key Concepts

### ReAct Pattern
ReAct (Reasoning + Acting) lets the LLM reason about which tools to use:
```python
agent = dspy.ReAct(
    signature="question -> answer",
    tools=[search, calculate],
)
```

### Tools
Regular Python functions with docstrings:
```python
def search(query: str) -> str:
    """Search for information about a topic."""
    return "..."
```

### Signatures
Declarative input/output specs:
```python
"question -> answer"  # Takes question, returns answer
```

## References

- [DSPy Docs](https://dspy.ai/)
- [ReAct Module](https://dspy.ai/api/modules/ReAct/)
