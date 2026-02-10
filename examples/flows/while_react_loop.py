"""
ReAct (Reasoning + Acting) loop pattern.

Primary use case for while loops: an LLM agent that iterates
calling an LLM and executing tools until no more tool calls remain.
"""


def react_agent(p: dict) -> dict:
    while True:
        p = llm_call(p)
        if p.get("tool_calls"):
            p = execute_tool(p)
        else:
            return p
    return p


def llm_call(p: dict) -> dict:
    """Call the LLM with the current state."""
    return p


def execute_tool(p: dict) -> dict:
    """Execute tool calls requested by the LLM."""
    return p
