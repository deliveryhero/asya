"""
Tool-Calling Agent - using typed tool functions directly in flows.

An LLM-driven agent that calls typed tool functions (weather, search, etc.)
without manually writing adapter boilerplate. The compiler detects non-standard
call signatures (p["key"] = fn(p["arg"])) and auto-generates adapter wrappers.

Three ways to mark a function as an adapter actor:

1. @tool decorator (matched by compiler rule, auto-stripped)
2. # asya: actor inline directive (works with any function)
3. Rule engine match on import path

The compiler generates adapter actors that bridge between the mesh's
dict-in/dict-out protocol and the tool's typed signature.

Pattern: LLM reason -> conditional tool dispatch -> adapter actors -> loop

ADK equivalent:
  - Function tools with FunctionTool.from_function()
  - https://google.github.io/adk-docs/tools/function-tools/
  - ADK samples without decorators: plain functions registered as tools
    https://github.com/google/adk-samples/blob/main/python/agents/data-engineering/

Framework references:
  - Claude Agent SDK: @tool decorator for Python functions
    https://github.com/anthropics/claude-agent-sdk-python
  - LangGraph: from langchain_core.tools import tool
    https://python.langchain.com/docs/how_to/custom_tools/
  - Anthropic: tool_use blocks in Claude API responses
    https://docs.anthropic.com/en/docs/build-with-claude/tool-use

Deployment:
  - llm_reason: LLM actor (picks tools, produces final answer)
  - get_weather: adapter actor (async, @tool decorator)
  - web_search: adapter actor (async, @tool decorator)
  - calculate: adapter actor (sync, @tool decorator)
  - list_gcs_files: adapter actor (async, no decorator, # asya: actor directive)
  - format_response: standard dict->dict actor

Payload contract:
  p["messages"]     - conversation history
  p["tool_name"]    - which tool the LLM selected (or None for final answer)
  p["tool_args"]    - arguments for the selected tool
  p["tool_result"]  - result from tool execution
  p["response"]     - final formatted response

Compiler rules (.asya/config.compiler.rules.yaml):
  - match: "claude_agent_sdk.tool"
    treat-as: actor
"""

from _asya_utils import flow

# -- Tool definitions with @tool decorator --
# In a real project these would import from claude_agent_sdk or langchain.
# The @tool decorator is recognized by compiler rules and auto-stripped.


def tool(f):
    return f


@tool
async def get_weather(city: str, units: str = "celsius") -> dict:
    """Get current weather for a city."""
    ...


@tool
async def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web and return results."""
    ...


# Sync tool — compiler generates def (not async def) adapter
@tool
def calculate(expression: str) -> dict:
    """Evaluate a math expression. Sync — no await needed."""
    ...


# -- ADK-style tool: plain function, no decorator --
# Tools from frameworks like Google ADK don't use decorators at all.
# Use the # asya: actor directive to tell the compiler this is an actor.
# See: https://github.com/google/adk-samples/blob/main/python/agents/data-engineering/


async def list_gcs_files(bucket: str, prefix: str) -> dict:
    """List files in a GCS bucket. No decorator needed."""
    ...


# -- Flow definition --


@flow
async def tool_calling_agent(p: dict) -> dict:
    """Agent that calls tools based on LLM decisions."""
    p["messages"] = p.get("messages", [])
    p["iteration"] = 0

    while True:
        p["iteration"] += 1

        # LLM picks a tool or produces final answer
        p = await llm_reason(p)

        if not p.get("tool_name"):
            break

        # Dispatch to the right tool via adapter actors.
        # The compiler detects p["tool_result"] = fn(p["arg"]) as an adapter
        # pattern and generates wrapper code automatically.
        if p["tool_name"] == "get_weather":
            p["tool_result"] = await get_weather(p["tool_args"]["city"])  # asya: actor
        elif p["tool_name"] == "web_search":
            p["tool_result"] = await web_search(p["tool_args"]["query"])  # asya: actor
        elif p["tool_name"] == "calculate":
            # Sync tool — compiler generates sync adapter (no await)
            p["tool_result"] = calculate(p["tool_args"]["expression"])  # asya: actor
        elif p["tool_name"] == "list_gcs_files":
            # Plain function (ADK-style, no decorator) — directive marks it as actor
            p["tool_result"] = await list_gcs_files(p["tool_args"]["bucket"], p["tool_args"]["prefix"])  # asya: actor

        # Append observation to message history
        p["messages"] = p["messages"] + [{"role": "tool", "content": p["tool_result"]}]

    p = await format_response(p)
    return p
