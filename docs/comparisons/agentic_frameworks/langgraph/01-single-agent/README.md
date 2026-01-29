# LangGraph Single Agent Example

Minimal working example demonstrating a single agent with tools using LangGraph's StateGraph.

## Overview

This example implements a simple agent that:
1. Receives user queries
2. Calls appropriate tools based on LLM decisions
3. Returns final responses

**Key LangGraph concepts**:
- **StateGraph**: Graph that maintains and updates shared state
- **Tool binding**: `llm.bind_tools(tools)` enables LLM to call tools
- **Conditional routing**: Routes to tools or end based on LLM response
- **Tool execution**: Separate node for executing tool calls

## Architecture

```
User Input
    ↓
[START] → [agent] → [should_use_tools?] → [END] (if no tools)
                         ↓
                      [tools] → [agent] (loop back)
```

**Flow**:
1. `agent` node: LLM receives messages and decides whether to call tools
2. `should_use_tools`: Conditional edge - if last message has tool_calls, route to tools
3. `tools` node: Execute called tools, add results to message history
4. Loop back to agent until LLM produces final response
5. End when no more tool calls

## Tools

Three mock tools demonstrate tool usage:

- **get_weather(location)**: Returns mock weather for a city
- **calculate_distance(from, to)**: Returns distance between locations
- **get_population(location)**: Returns population data

Mock data is hardcoded; no real API calls.

## State Management

Uses simple `State` class with `messages` list:

```python
class State:
    messages: list[BaseMessage]
```

**State updates**:
- `agent` node appends AIMessage with tool calls
- `tools` node appends ToolMessages with results
- State flows through entire conversation until completion

## Setup

### Prerequisites

- Python 3.10+
- Anthropic API key (required for Claude model)

### Installation

```bash
# From langgraph/ directory
pip install -e .
```

Or install directly:

```bash
pip install langgraph>=0.2.0 langchain>=0.2.0 langchain-anthropic>=0.1.0
```

### Environment

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

## Running

```bash
# From this directory
cd docs/comparisons/agentic_frameworks/langgraph/01-single-agent
python main.py
```

## Example Output

```
User: What's the weather in San Francisco?
------------------------------------------------------------
Agent: The weather in San Francisco is partly cloudy with a temperature of 52°F and light winds.
------------------------------------------------------------

User: How far is it from New York to Boston?
------------------------------------------------------------
Agent: The distance from New York to Boston is 215 miles.
------------------------------------------------------------

User: What's the population of London and Tokyo?
------------------------------------------------------------
Agent: London has a population of 9 million people, while Tokyo has a population of 37.4 million people.
------------------------------------------------------------
```

## Key Differences from Other Frameworks

| Aspect | LangGraph |
|--------|-----------|
| **State** | Explicit StateGraph with typed state class |
| **Tool Binding** | `llm.bind_tools(tools)` on model directly |
| **Routing** | Conditional edges based on function output |
| **Tool Execution** | Manual tool execution with ToolMessage wrapping |
| **State Updates** | Explicit dict returns from nodes |

## Design Notes

### Message-Centric State

LangGraph uses message lists as primary state:
- Each tool call creates new AIMessage with `tool_calls` attribute
- Tool results wrapped in ToolMessage
- Message history preserved for context

### Explicit Routing

Conditional edges explicitly check LLM response structure:

```python
def should_use_tools(state: State) -> str:
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END
```

### Tool Execution

LangGraph leaves tool invocation to the developer (or ToolNode helper):

```python
for tool_call in last_message.tool_calls:
    tool_name = tool_call["name"]
    tool_input = tool_call["args"]
    # Execute tool...
```

## Further Reading

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [StateGraph API](https://langchain-ai.github.io/langgraph/reference/graphs/#langgraph.graph.StateGraph)
- [Tool Calling in LangChain](https://python.langchain.com/docs/concepts/tool_calling)
