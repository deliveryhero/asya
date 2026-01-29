# Single Agent Example - OpenAI Agents SDK

A minimal working example demonstrating a single agent with tools using the OpenAI Agents SDK.

## Overview

This example shows:
- Creating an `Agent` with instructions and model configuration
- Defining tools using the `@function_tool` decorator
- Running the agent using the `Runner.run()` async pattern
- Agent tool invocation with automatic function calling

## Tools Included

1. **get_current_time()** - Returns the current date and time
2. **add_numbers(a, b)** - Performs basic arithmetic
3. **greet_user(name)** - Returns a personalized greeting

## Setup

### Prerequisites

- Python 3.9 or higher
- OpenAI API key (set `OPENAI_API_KEY` environment variable)

### Installation

```bash
# Install dependencies
pip install -e ..

# Or directly install OpenAI Agents SDK
pip install openai-agents>=0.7.0
```

### Environment Setup

Set your OpenAI API key:

```bash
export OPENAI_API_KEY="your-api-key-here"
```

## Running the Example

```bash
python agent.py
```

### Expected Output

```
============================================================
OpenAI Agents SDK - Single Agent Example
============================================================

User: What time is it right now?
------------------------------------------------------------
Agent: The current time is [ISO timestamp]

User: What is 15 plus 27?
------------------------------------------------------------
Agent: 15 plus 27 equals 42.

User: Please greet Alice
------------------------------------------------------------
Agent: Hello, Alice! Welcome to the OpenAI Agents SDK example.

============================================================
```

## Code Explanation

### Agent Definition

```python
agent = Agent(
    name="Assistant",
    instructions="You are a helpful assistant...",
    model="gpt-4o-mini",
    tools=[get_current_time, add_numbers, greet_user],
)
```

The `Agent` class takes:
- `name`: Display name for the agent
- `instructions`: System prompt describing agent behavior
- `model`: OpenAI model to use (e.g., "gpt-4o-mini")
- `tools`: List of tools the agent can invoke

### Tool Definition

```python
@function_tool
def get_current_time() -> str:
    """Get the current date and time.

    Returns:
        Current timestamp in ISO format
    """
    return datetime.now().isoformat()
```

The `@function_tool` decorator:
- Converts the function into a tool schema
- Uses docstring and type annotations for agent understanding
- Automatically handles function invocation

### Runner Pattern

```python
result = await Runner.run(agent, prompt)
print(result.final_output)
```

`Runner.run()`:
- Executes the agent asynchronously
- Handles tool invocation loops
- Returns a `RunResult` with `final_output`

For synchronous execution, use `Runner.run_sync()`:

```python
result = Runner.run_sync(agent, prompt)
```

## Key Features

- **Minimal setup**: Only 3 lines for agent creation
- **Type-safe tools**: Type annotations guide agent behavior
- **Async support**: Native async/await pattern
- **Mock tools**: No external API calls, safe for testing
- **Clear documentation**: Each tool has descriptive docstring

## Next Steps

- Add more complex tools
- Implement multi-agent handoffs
- Add input/output guardrails
- Use `Runner.run_streamed()` for streaming responses

## Resources

- [OpenAI Agents SDK Documentation](https://openai.github.io/openai-agents-python/)
- [Quickstart Guide](https://openai.github.io/openai-agents-python/quickstart/)
- [Tools Documentation](https://openai.github.io/openai-agents-python/ref/tool/)
- [Running Agents Guide](https://openai.github.io/openai-agents-python/running_agents/)
