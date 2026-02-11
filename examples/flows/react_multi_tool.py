"""
ReAct loop with multiple tools - ADK multi-tool agent pattern.

A research agent that dispatches to different tool handlers based
on the tool name returned by the LLM. Demonstrates conditional
tool routing inside a ReAct loop.
"""

from collections.abc import AsyncGenerator


async def research_agent(state: dict) -> AsyncGenerator[dict, None]:
    state["messages"] = state.get("messages", [])
    while True:
        state = await llm_call(state)
        tool_name = state.get("tool_name")
        if tool_name == "search":
            state = await web_search(state)
        elif tool_name == "calculator":
            state = await calculator(state)
        elif tool_name == "code_exec":
            state = await code_executor(state)
        else:
            yield {"type": "result", **state}
            return


async def llm_call(state: dict) -> dict:
    """Call LLM with conversation history and available tools."""
    return state


async def web_search(state: dict) -> dict:
    """Search the web and return results."""
    return state


async def calculator(state: dict) -> dict:
    """Evaluate mathematical expressions."""
    return state


async def code_executor(state: dict) -> dict:
    """Execute code in a sandboxed environment."""
    return state
