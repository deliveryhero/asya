"""
Single Agent with Tools using LangGraph StateGraph.

Demonstrates:
- StateGraph for managing agent state
- Tool binding with llm.bind_tools()
- Tool node execution
- Conditional routing based on tool calls
"""

from typing import Any
import json
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic


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


# Define state schema
class State:
    """Agent state containing messages."""
    messages: list[BaseMessage]


def should_use_tools(state: State) -> str:
    """Route: if LLM calls tools, go to tool_node, else end."""
    messages = state["messages"]
    last_message = messages[-1]

    # If last message has tool calls, use tools
    if last_message.tool_calls:
        return "tools"
    # Otherwise, end conversation
    return END


def agent_node(state: State) -> dict[str, Any]:
    """Agent node: call LLM with tools bound."""
    messages = state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def tool_node(state: State) -> dict[str, Any]:
    """Tool node: execute called tools and add results to messages."""
    messages = state["messages"]
    last_message = messages[-1]

    # Execute each tool call
    tool_results = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_input = tool_call["args"]

        # Call appropriate tool
        if tool_name == "get_weather":
            result = get_weather.invoke(tool_input)
        elif tool_name == "calculate_distance":
            result = calculate_distance.invoke(tool_input)
        elif tool_name == "get_population":
            result = get_population.invoke(tool_input)
        else:
            result = f"Unknown tool: {tool_name}"

        tool_results.append({
            "tool_call_id": tool_call["id"],
            "result": result,
        })

    # Create tool result message
    from langchain_core.messages import ToolMessage
    tool_messages = [
        ToolMessage(
            content=result["result"],
            tool_call_id=result["tool_call_id"],
        )
        for result in tool_results
    ]

    return {"messages": tool_messages}


# Initialize LLM with tools
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
tools = [get_weather, calculate_distance, get_population]
llm_with_tools = llm.bind_tools(tools)

# Build graph
graph_builder = StateGraph(State)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("tools", tool_node)

# Add edges
graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges("agent", should_use_tools)
graph_builder.add_edge("tools", "agent")

# Compile graph
graph = graph_builder.compile()


def run_agent(user_input: str) -> None:
    """Run the agent with a user input."""
    print(f"\nUser: {user_input}")
    print("-" * 60)

    # Create initial state
    messages = [HumanMessage(content=user_input)]
    state = {"messages": messages}

    # Run graph until END
    final_state = graph.invoke(state)

    # Extract and print final response
    final_message = final_state["messages"][-1]
    if isinstance(final_message, AIMessage):
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
