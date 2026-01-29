# Single Agent with Anthropic SDK

Minimal working example of an AI agent using the Anthropic Python SDK with the tool use pattern.

## Overview

This example demonstrates the core agent loop:

1. **Define tools** with JSON schema describing capabilities
2. **Send user message** to Claude along with available tools
3. **Process tool calls** when Claude decides to use a tool
4. **Return results** back to Claude for further reasoning
5. **Repeat** until Claude provides a final response

## Architecture

```
User Message
    ↓
Claude API (with tools)
    ↓
Is response a tool call?
    ├─ Yes: Execute tool → Add result to messages → Loop back to Claude
    └─ No: Return final response
```

## Files

- `agent.py` - Single-agent implementation with tool execution loop
- `README.md` - This file

## Setup

### Prerequisites

- Python 3.9+
- Anthropic API key

### Installation

1. Install dependencies:
```bash
cd /path/to/docs/comparisons/agentic_frameworks/anthropic-sdk
pip install -e .
```

Or manually:
```bash
pip install 'anthropic>=0.28.0'
```

2. Set your API key:
```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

## Running the Example

```bash
python 01-single-agent/agent.py
```

## Key Concepts

### Tool Definition (JSON Schema)

Each tool requires:
- **name**: Unique identifier
- **description**: What the tool does
- **input_schema**: JSON Schema describing parameters

```python
{
    "name": "get_current_time",
    "description": "Get the current time in a specified timezone",
    "input_schema": {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "Timezone (e.g., 'UTC', 'US/Eastern')",
            }
        },
        "required": ["timezone"],
        "additionalProperties": False,
    },
}
```

### Agent Loop

1. Send user message + tools to Claude API
2. Check response.stop_reason:
   - If `"tool_use"`: Extract tool call, execute, send result back, loop
   - If `"end_turn"`: Extract final text response and return

### Tools in Example

The example includes 3 mock tools:

1. **get_current_time** - Returns mock time in different timezones
2. **calculate_sum** - Sums a list of numbers
3. **get_user_info** - Returns mock user data by ID

All tools are mock implementations (no external API calls).

## Code Structure

- `tools` - List of tool definitions with JSON schemas
- `get_current_time()`, `calculate_sum()`, `get_user_info()` - Mock tool implementations
- `process_tool_call()` - Routes tool calls to implementations
- `run_single_agent()` - Main agent loop that calls Claude and processes results
- `main()` - Runs 4 test scenarios

## Extending the Example

To add new tools:

1. Add tool definition to `tools` list
2. Implement the mock function
3. Add case to `process_tool_call()`
4. Call `run_single_agent()` with a test message

Example:
```python
def my_tool(param: str) -> str:
    return f"Processed {param}"

# Add to tools list:
{
    "name": "my_tool",
    "description": "My custom tool",
    "input_schema": {
        "type": "object",
        "properties": {
            "param": {"type": "string"}
        },
        "required": ["param"],
        "additionalProperties": False,
    }
}
```

## References

- [Anthropic Tool Use Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
- [JSON Schema Format](https://json-schema.org/)
