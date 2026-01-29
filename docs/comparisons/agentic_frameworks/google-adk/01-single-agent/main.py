"""Minimal single-agent example for Google ADK.

This example demonstrates:
- Creating an LlmAgent with mock tools
- Using InMemoryRunner for testing without external services
- Running the agent with queries via run_async()
"""

import asyncio
from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types


def get_weather(city: str) -> dict:
    """Get the current weather for a city.

    Args:
        city: Name of the city (case-insensitive)

    Returns:
        Dictionary with weather information or error message
    """
    weather_data = {
        "new york": "sunny, 25C",
        "london": "cloudy, 15C",
        "tokyo": "rainy, 20C",
        "paris": "clear, 18C",
    }

    city_lower = city.lower()
    if city_lower in weather_data:
        return {
            "status": "success",
            "weather": f"The weather in {city} is {weather_data[city_lower]}"
        }
    else:
        return {
            "status": "error",
            "message": f"Weather data not available for '{city}'"
        }


def calculate(expression: str) -> dict:
    """Evaluate a simple mathematical expression.

    Args:
        expression: A mathematical expression (e.g., "2 + 3 * 4")

    Returns:
        Dictionary with the calculation result or error message
    """
    try:
        result = eval(expression)
        return {
            "status": "success",
            "result": result,
            "expression": expression
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Could not evaluate '{expression}': {str(e)}"
        }


def get_capital(country: str) -> dict:
    """Get the capital city of a country.

    Args:
        country: Name of the country

    Returns:
        Dictionary with the capital city or error message
    """
    capitals = {
        "france": "Paris",
        "japan": "Tokyo",
        "usa": "Washington, D.C.",
        "uk": "London",
        "germany": "Berlin",
        "italy": "Rome",
    }

    country_lower = country.lower()
    if country_lower in capitals:
        return {
            "status": "success",
            "capital": capitals[country_lower],
            "country": country
        }
    else:
        return {
            "status": "error",
            "message": f"Capital information not available for '{country}'"
        }


async def main():
    """Initialize and run the agent."""
    # Create the agent with tools
    agent = LlmAgent(
        name="helpful_assistant",
        model="gemini-2.0-flash",
        description="A helpful assistant that can answer questions about weather, perform calculations, and provide geography information.",
        instruction="You are a helpful assistant. Use the available tools to answer user questions accurately and helpfully.",
        tools=[get_weather, calculate, get_capital],
    )

    # Create an in-memory runner for testing
    runner = InMemoryRunner(agent=agent, app_name="single-agent-example")

    # Sample queries to demonstrate the agent
    queries = [
        "What is the weather in Paris?",
        "Calculate 15 * 8 + 42",
        "What is the capital of Japan?",
    ]

    print("=" * 60)
    print("Google ADK Single-Agent Example")
    print("=" * 60)

    async with runner:
        for query in queries:
            print(f"\nUser: {query}")
            print("-" * 60)

            # Execute the agent with the query
            content = types.Content(
                role="user",
                parts=[types.Part(text=query)]
            )

            response_text = ""
            async for event in runner.run_async(
                user_id="test-user",
                session_id="test-session",
                new_message=content,
            ):
                # Collect text parts from model responses
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, 'text') and part.text:
                            response_text += part.text

            print(f"Agent: {response_text}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
