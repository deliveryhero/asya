"""
ReAct loop - ADK LlmAgent with tools pattern.

An LLM agent iterates: call the model, check for tool calls,
execute tools, and loop until the model produces a final answer.
Uses AsyncGenerator to yield intermediate results.

Reference: https://github.com/google/adk-samples/tree/main/python/agents/llm-auditor
"""

from collections.abc import AsyncGenerator


async def agent_with_tools(state: dict) -> AsyncGenerator[dict, None]:
    state["messages"] = state.get("messages", [])
    while True:
        state = await llm_call(state)
        if state.get("tool_calls"):
            state = await execute_tool(state)
        else:
            yield {"type": "result", **state}
            return


async def llm_call(state: dict) -> dict:
    """Call LLM with conversation history and available tools."""
    return state


async def execute_tool(state: dict) -> dict:
    """Execute tool calls requested by the LLM."""
    return state
