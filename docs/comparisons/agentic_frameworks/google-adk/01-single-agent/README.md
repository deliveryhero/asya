# Google ADK Single-Agent Example

A minimal working example of a single agent using Google's Agent Development Kit (ADK).

## Overview

This example demonstrates:
- **Agent Creation**: Using ADK's `LlmAgent` class with model, instructions, and tools
- **Tool Integration**: Defining mock tools (get_weather, calculate, get_capital) using simple Python functions
- **Agent Execution**: Running the agent with sample queries via `Runner` and `InMemorySessionService`
- **Standard Gemini**: Using Gemini 2.0 Flash model for LLM capabilities

## File Structure

```
google-adk/
├── pyproject.toml                 # Python dependencies (google-adk)
└── 01-single-agent/
    ├── agent.py                    # Agent implementation with tools
    └── README.md                  # This file
```

## Setup

### Prerequisites
- Python 3.10+ (3.13+ recommended)
- `uv` or `pip` for dependency management
- Google API key with Gemini API access

### Install Dependencies

Using `uv` (recommended):
```bash
cd docs/comparisons/agentic_frameworks/google-adk
uv sync
```

Or using `pip`:
```bash
cd docs/comparisons/agentic_frameworks/google-adk
pip install google-adk
```

### Set Up API Key

```bash
export GOOGLE_API_KEY="your-api-key-here"
```

Get your API key from [Google AI Studio](https://aistudio.google.com/app/apikey).

## Run the Example

From the `google-adk/` directory:

```bash
uv run 01-single-agent/agent.py
```

Or with Python directly:
```bash
python 01-single-agent/agent.py
```

## Example Output

```
============================================================
Google ADK Single-Agent Example
============================================================

User: What is the weather in Paris?
------------------------------------------------------------
Agent: The weather in Paris is clear, 18°C

User: Calculate 15 * 8 + 42
------------------------------------------------------------
Agent: 15 * 8 + 42 = 162

User: What is the capital of Japan?
------------------------------------------------------------
Agent: The capital of Japan is Tokyo
```

## Code Structure

### Tools
Three mock tools are defined as Python functions:

1. **`get_weather(city: str)`** - Returns hardcoded weather data for sample cities
2. **`calculate(expression: str)`** - Evaluates mathematical expressions
3. **`get_capital(country: str)`** - Returns capital cities for sample countries

Each tool includes:
- Clear function name (used by the model to understand purpose)
- Type hints for parameters (enables the model to use them correctly)
- Docstring explaining what it does (helps the model decide when to use it)

### Agent Definition

```python
agent = LlmAgent(
    name="helpful_assistant",
    model="gemini-2.0-flash",
    description="A helpful assistant that can answer questions...",
    instruction="You are a helpful assistant...",
    tools=[get_weather, calculate, get_capital],
)
```

Key components:
- **name**: Agent identifier
- **model**: The LLM powering the agent (Gemini 2.0 Flash)
- **description**: What the agent does (for documentation)
- **instruction**: System prompt guiding the agent's behavior
- **tools**: List of functions the agent can call

### Execution

```python
session_service = InMemorySessionService()
runner = Runner(agent=agent, app_name="single-agent-example", session_service=session_service)

async for event in runner.run_async(
    user_id="test-user",
    session_id="test-session",
    new_message=content,
):
    # Process events
```

- **InMemorySessionService**: Stores conversation history in memory (enables multi-turn conversations)
- **Runner**: Executes the agent asynchronously, handling tool calling and orchestration
- **run_async**: Streams events from agent execution

## Extending the Example

To add more tools:

1. Define a new Python function with clear name, type hints, and docstring:
   ```python
   def my_tool(param: str) -> dict:
       """Tool description here."""
       return {"result": "..."}
   ```

2. Add it to the agent's tools list:
   ```python
   agent = LlmAgent(
       ...
       tools=[get_weather, calculate, get_capital, my_tool],
   )
   ```

## Key Concepts

- **Tools as Functions**: ADK tools are simply Python functions with proper signatures
- **Type Hints Matter**: The model uses type hints to understand parameter types
- **Docstrings as Specs**: Function docstrings tell the model what each tool does
- **Mock Data**: This example uses hardcoded responses for simplicity (no real API calls)

## Resources

- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [ADK Tools Guide](https://google.github.io/adk-docs/tools/)
- [ADK Quickstart](https://google.github.io/adk-docs/get-started/quickstart/)
