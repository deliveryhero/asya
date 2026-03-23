"""
Multi-Tool Pipeline - sequential tool calls with data dependencies.

A pipeline that chains multiple typed tool functions where each tool's output
feeds into the next. Uses LangGraph/LangChain-style @tool decorator from
langchain_core.tools.

Unlike the ReAct loop (dynamic tool selection), this is a fixed pipeline
where the tool sequence is known at compile time. Each tool extracts specific
fields from the payload and writes its result to a specific key.

Pattern: extract -> tool_1 -> tool_2 -> tool_3 -> aggregate

ADK equivalent:
  - SequentialAgent with FunctionTool steps
  - https://google.github.io/adk-docs/agents/workflow-agents/sequential-agent/

Framework references:
  - LangGraph: @tool from langchain_core.tools
    https://python.langchain.com/docs/how_to/custom_tools/
  - Anthropic: chaining tool calls in a fixed sequence
    https://docs.anthropic.com/en/docs/build-with-claude/tool-use

Deployment:
  - geocode: adapter actor (string -> coordinates)
  - get_weather: adapter actor (coordinates -> forecast)
  - translate: adapter actor (text -> translated text)
  - summarize: standard dict->dict actor (final formatting)

Payload contract:
  p["location"]      - user-provided location string
  p["language"]       - target language for translation
  p["coordinates"]    - {lat, lng} from geocoding
  p["forecast"]       - weather data from API
  p["translated"]     - forecast translated to target language
  p["summary"]        - final human-readable summary

Compiler rules:
  langchain_core.tools.tool is a shipped default rule (treat-as: actor).
  The @tool decorator is auto-stripped at compile time.
"""

from _asya_utils import flow

# In a real project: from langchain_core.tools import tool
# The compiler matches "langchain_core.tools.tool" via default rules.
# Here we use a no-op stub since langchain_core is not a project dependency.


def tool(f):
    return f


@tool
async def geocode(location: str) -> dict:
    """Convert a location string to lat/lng coordinates."""
    ...


@tool
async def get_weather(lat: float, lng: float) -> dict:
    """Get weather forecast for coordinates."""
    ...


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two numbers. Sync tool, no await needed."""
    return a * b


@tool
async def translate(text: str, target_language: str) -> dict:
    """Translate text to a target language."""
    ...


@flow
async def multi_tool_pipeline(p: dict) -> dict:
    """Chain typed tools: geocode -> weather -> translate -> summarize."""

    # Each line maps payload fields to tool args and captures the result.
    # The compiler generates adapter wrappers for each @tool function.

    p["coordinates"] = await geocode(p["location"])  # asya: actor

    p["forecast"] = await get_weather(  # asya: actor
        p["coordinates"]["lat"],
        p["coordinates"]["lng"],
    )

    # Sync tool call (no await) — compiler detects and generates sync adapter
    p["scaled"] = multiply(p["forecast"]["temp"], p["scale_factor"])  # asya: actor

    p["translated"] = await translate(  # asya: actor
        p["forecast"]["description"],
        p["language"],
    )

    # Standard dict->dict actor for final formatting
    p = await summarize(p)

    return p
