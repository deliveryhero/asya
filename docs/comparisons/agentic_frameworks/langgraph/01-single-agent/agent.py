"""
Single Agent with Tools using LangGraph create_react_agent (prebuilt).

Demonstrates:
- Official prebuilt create_react_agent pattern
- Tool binding with language model
- Automatic tool node execution
- Built-in conditional routing
"""

from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage


# Define mock tools
@tool
def get_weather(location: str) -> str:
    """Get the weather for a given location.

    Args:
        location: City name or location string

    Returns:
        Weather description for the location
    """
    # Mock weather data
    weather_data = {
        "new york": "Cloudy, 45F, 10mph winds",
        "san francisco": "Partly cloudy, 52F, light winds",
        "london": "Rainy, 38F, moderate winds",
        "tokyo": "Clear, 62F, calm",
    }
    return weather_data.get(location.lower(), f"Weather data for {location} not available")


@tool
def calculate_distance(from_location: str, to_location: str) -> str:
    """Calculate the distance between two locations.

    Args:
        from_location: Starting location
        to_location: Destination location

    Returns:
        Distance in miles
    """
    # Mock distance data
    distances = {
        ("new york", "boston"): 215,
        ("san francisco", "los angeles"): 383,
        ("london", "paris"): 215,
        ("tokyo", "osaka"): 280,
    }

    pair = tuple(sorted([from_location.lower(), to_location.lower()]))
    distance = distances.get(pair)

    if distance:
        return f"Distance from {from_location} to {to_location} is {distance} miles"
    return f"Distance data not available for {from_location} and {to_location}"


@tool
def get_population(location: str) -> str:
    """Get the population of a location.

    Args:
        location: City or country name

    Returns:
        Population information
    """
    # Mock population data
    populations = {
        "new york": "8.3 million",
        "san francisco": "883 thousand",
        "london": "9 million",
        "tokyo": "37.4 million",
    }
    return populations.get(
        location.lower(),
        f"Population data for {location} not available"
    )


# Initialize LLM
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
tools = [get_weather, calculate_distance, get_population]

# Build agent using official prebuilt pattern
graph = create_react_agent(llm, tools)


def run_agent(user_input: str) -> None:
    """Run the agent with a user input."""
    print(f"\nUser: {user_input}")
    print("-" * 60)

    # Create initial state with messages
    state = {"messages": [HumanMessage(content=user_input)]}

    # Run graph until END
    final_state = graph.invoke(state)

    # Extract and print final response
    final_message = final_state["messages"][-1]
    print(f"Agent: {final_message.content}")
    print("-" * 60)


if __name__ == "__main__":
    # Example queries
    queries = [
        "What's the weather in San Francisco?",
        "How far is it from New York to Boston?",
        "What's the population of London and Tokyo?",
    ]

    for query in queries:
        run_agent(query)
