"""
Minimal single-agent example using OpenAI Agents SDK.

This example demonstrates:
1. Creating an agent with instructions
2. Defining tools using the @function_tool decorator
3. Running the agent using the Runner pattern
"""

import asyncio
from datetime import datetime

from agents import Agent, Runner, function_tool


@function_tool
def get_current_time() -> str:
    """Get the current date and time.

    Returns:
        Current timestamp in ISO format
    """
    return datetime.now().isoformat()


@function_tool
def add_numbers(a: float, b: float) -> float:
    """Add two numbers together.

    Args:
        a: First number
        b: Second number

    Returns:
        Sum of a and b
    """
    return a + b


@function_tool
def greet_user(name: str) -> str:
    """Greet a user by name.

    Args:
        name: The name of the person to greet

    Returns:
        A friendly greeting message
    """
    return f"Hello, {name}! Welcome to the OpenAI Agents SDK example."


async def main():
    """Create and run a single agent with tools."""

    agent = Agent(
        name="Assistant",
        instructions=(
            "You are a helpful assistant. Use your tools to help the user. "
            "When asked about time, use the get_current_time tool. "
            "When asked to perform math, use the add_numbers tool. "
            "When asked to greet someone, use the greet_user tool."
        ),
        model="gpt-4o-mini",
        tools=[get_current_time, add_numbers, greet_user],
    )

    print("=" * 60)
    print("OpenAI Agents SDK - Single Agent Example")
    print("=" * 60)

    prompts = [
        "What time is it right now?",
        "What is 15 plus 27?",
        "Please greet Alice",
    ]

    for prompt in prompts:
        print(f"\nUser: {prompt}")
        print("-" * 60)

        result = await Runner.run(agent, prompt)

        print(f"Agent: {result.final_output}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
