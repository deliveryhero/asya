#!/usr/bin/env python3
"""
Minimal single-agent example using Anthropic SDK with tool use pattern.

This example demonstrates:
- Defining tools with JSON schema
- Making API calls with tool_use support
- Executing tools and returning results back to Claude
"""

import json
from anthropic import Anthropic

# Initialize the Anthropic client (uses ANTHROPIC_API_KEY environment variable)
client = Anthropic()

# Define tools with JSON schema
tools = [
    {
        "name": "get_current_time",
        "description": "Get the current time in a specified timezone",
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "Timezone (e.g., 'UTC', 'US/Eastern', 'Europe/London')",
                }
            },
            "required": ["timezone"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calculate_sum",
        "description": "Calculate the sum of a list of numbers",
        "input_schema": {
            "type": "object",
            "properties": {
                "numbers": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "List of numbers to sum",
                }
            },
            "required": ["numbers"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_user_info",
        "description": "Get information about a user by ID",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to look up",
                }
            },
            "required": ["user_id"],
            "additionalProperties": False,
        },
    },
]


def get_current_time(timezone: str) -> str:
    """Mock tool: Get current time in timezone"""
    time_map = {
        "UTC": "14:30:00 UTC",
        "US/Eastern": "09:30:00 EST",
        "Europe/London": "14:30:00 GMT",
        "Asia/Tokyo": "23:30:00 JST",
    }
    return time_map.get(timezone, f"Unknown timezone: {timezone}")


def calculate_sum(numbers: list) -> float:
    """Mock tool: Calculate sum of numbers"""
    return sum(numbers)


def get_user_info(user_id: int) -> dict:
    """Mock tool: Get user information"""
    users = {
        1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
        2: {"id": 2, "name": "Bob", "email": "bob@example.com"},
        3: {"id": 3, "name": "Charlie", "email": "charlie@example.com"},
    }
    return users.get(user_id, {"error": f"User {user_id} not found"})


def process_tool_call(tool_name: str, tool_input: dict) -> str:
    """Execute a tool based on name and input"""
    if tool_name == "get_current_time":
        result = get_current_time(tool_input["timezone"])
    elif tool_name == "calculate_sum":
        result = calculate_sum(tool_input["numbers"])
    elif tool_name == "get_user_info":
        result = get_user_info(tool_input["user_id"])
    else:
        result = f"Unknown tool: {tool_name}"

    return json.dumps(result) if isinstance(result, (dict, list)) else str(result)


def run_single_agent(user_message: str) -> str:
    """
    Run the single-agent loop:
    1. Send user message + tools to Claude
    2. If Claude responds with tool_use, execute the tool
    3. Send tool result back to Claude
    4. Return final response
    """
    messages = [
        {"role": "user", "content": user_message}
    ]

    print(f"\n{'='*60}")
    print(f"User: {user_message}")
    print(f"{'='*60}")

    # Initial API call with tools
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        tools=tools,
        messages=messages,
    )

    # Agentic loop: keep processing until we get a final response
    while response.stop_reason == "tool_use":
        # Find the tool_use block
        tool_use_block = None
        for block in response.content:
            if block.type == "tool_use":
                tool_use_block = block
                break

        if not tool_use_block:
            break

        tool_name = tool_use_block.name
        tool_input = tool_use_block.input
        tool_use_id = tool_use_block.id

        print(f"\nTool called: {tool_name}")
        print(f"Input: {json.dumps(tool_input, indent=2)}")

        # Execute the tool
        tool_result = process_tool_call(tool_name, tool_input)
        print(f"Result: {tool_result}")

        # Add assistant response to messages
        messages.append({"role": "assistant", "content": response.content})

        # Add tool result to messages
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": tool_result,
                }
            ],
        })

        # Continue the conversation
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            tools=tools,
            messages=messages,
        )

    # Extract final text response
    final_response = ""
    for block in response.content:
        if hasattr(block, "text"):
            final_response += block.text

    print(f"\nAssistant: {final_response}")
    return final_response


def main():
    """Run example conversations"""
    # Example 1: Time query
    run_single_agent("What time is it in US/Eastern and Europe/London?")

    # Example 2: Calculation
    run_single_agent("What is the sum of 42, 17, and 23?")

    # Example 3: User lookup
    run_single_agent("Can you tell me about user 2?")

    # Example 4: Complex query with multiple tools
    run_single_agent("Get the current time in UTC, sum the numbers 10, 20, 30, and tell me about user 1")


if __name__ == "__main__":
    main()
