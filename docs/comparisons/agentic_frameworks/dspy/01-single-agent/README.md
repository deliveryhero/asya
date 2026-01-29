# DSPy Single Agent Example (ReAct Pattern)

Minimal working example of a single agent using DSPy's ReAct (Reasoning and Acting) pattern with tools.

## Key Concepts

**DSPy Philosophy**: "Programming, not prompting" - DSPy uses signatures for declarative task specification rather than hand-crafted prompts.

### Signatures
A signature specifies the input/output interface of an LM call:
```python
signature="question -> answer"  # Question in, answer out
```

### Modules
Reusable components that encapsulate LM calls:
```python
class MyAgent(dspy.Module):
    def __init__(self):
        self.agent = dspy.ReAct(signature="...", tools=[...])
```

### ReAct Pattern
Automatically handles reasoning and tool selection:
- LM receives a question and list of available tools
- LM decides which tool to call (or produce final answer)
- Tool result is fed back to LM for next iteration
- Process repeats up to `max_iters` times

### Tools
Regular Python functions with:
- **Docstring**: Describes what the tool does
- **Type hints**: Arguments and return type (required for LM to generate calls)

```python
def search_knowledge_base(query: str) -> str:
    """Search a knowledge base for information about a query."""
    ...
```

## Setup

### Prerequisites
- Python 3.10+
- OpenAI API key (for actual execution)

### Installation

Using uv:
```bash
cd docs/comparisons/agentic_frameworks/dspy/
uv pip install -e .
```

Or with pip:
```bash
cd docs/comparisons/agentic_frameworks/dspy/
pip install -e .
```

## Running

### With OpenAI API Key

```bash
export OPENAI_API_KEY="sk-..."
cd docs/comparisons/agentic_frameworks/dspy/01-single-agent/
python main.py
```

### Without API Key (Demo Mode)

```bash
cd docs/comparisons/agentic_frameworks/dspy/01-single-agent/
python main.py
```

This will demonstrate tool calls with mock output, showing how the agent would behave.

## Example Output

```
DSPy Single Agent (ReAct Pattern)
============================================================

Question: What is DSPy and how does it differ from other frameworks?
------------------------------------------------------------
Answer: DSPy is a framework for programming language models without prompting.
It uses signatures for declarative task specification. This differs from traditional
prompt engineering by providing a more structured, composable approach...

Reasoning: The agent used the search_knowledge_base tool to find information about DSPy.
```

## Implementation Details

### File Structure
```
01-single-agent/
├── main.py       # Single agent module with ReAct pattern
└── README.md     # This file
```

### Tools Included

1. **search_knowledge_base** - Query a mock knowledge base
2. **calculate_math** - Evaluate mathematical expressions
3. **get_definition** - Look up technical term definitions

All tools are fully mock-based (no real API calls), making the example runnable without external dependencies beyond the LM API.

### Agent Lifecycle

1. **Initialization**: Agent loads tools and creates ReAct module
2. **Question Processing**: Question is passed to ReAct agent
3. **Reasoning Loop** (up to max_iters):
   - LM receives question + available tools
   - LM generates tool call (or final answer)
   - Tool executes and returns result
   - Loop continues with tool result as context
4. **Answer Return**: Final answer returned to caller

## Comparison Notes

**DSPy vs Other Frameworks**:

| Aspect | DSPy | LangGraph | Anthropic SDK |
|--------|------|-----------|---------------|
| Philosophy | Programming-first | Graph-based flows | Tool-first API |
| State Model | Signatures + modules | Graph nodes | Context/memory |
| Tool Definition | Python functions | LangChain tools | Model tools |
| Learning Curve | Steeper (new paradigm) | Moderate | Shallow |

**For Asya**: DSPy's signature-based approach is closest to Asya's envelope routing - both define interfaces declaratively. However, DSPy is tightly coupled to LM APIs, whereas Asya decouples message routing from handler implementation.

## References

- [DSPy Official Docs](https://dspy.ai/)
- [DSPy ReAct Module](https://dspy.ai/api/modules/ReAct/)
- [DSPy Tools Documentation](https://dspy.ai/learn/programming/tools/)
- [DSPy GitHub](https://github.com/stanfordnlp/dspy)
