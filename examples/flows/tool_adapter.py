"""
Tool adapter flow - demonstrates @tool-decorated functions with non-standard signatures.

When an external framework (Claude Agent SDK, LangChain, etc.) defines a function with
typed parameters like `get_weather(city: str) -> dict` instead of Asya's `dict -> dict`
protocol, the compiler generates an adapter wrapper that bridges the two signatures.

Demonstrates:
- @tool decorator from claude_agent_sdk (auto-classified as actor via built-in rules)
- Non-standard function signatures: typed arguments extracted from payload keys
- Adapter code generation: compiler wraps the function for dict-in/dict-out protocol
- Mixing @tool-decorated actors with standard dict->dict actors in one flow
- Async and sync @tool functions in the same pipeline

The compiler generates an adapter file for each @tool-decorated function called with
non-standard arguments. For example:

    p["weather"] = await get_weather(p["city"])

becomes (in the generated adapter):

    async def adapter_get_weather(payload: dict):
        _result = await get_weather(payload["city"])
        payload["weather"] = _result
        yield payload

The adapter is deployed as a separate actor, bridging the tool's typed interface
with Asya's envelope protocol.
"""

from _asya_utils import actor, flow
from claude_agent_sdk import tool


@tool
async def get_weather(city: str, units: str = "celsius") -> dict:
    """Get current weather for a city."""
    return {"temp": 22, "condition": "sunny", "units": units}


@tool
def format_greeting(name: str) -> str:
    """Format a personalized greeting."""
    return f"Hello, {name}!"


@flow
async def tool_adapter(p: dict) -> dict:
    # Standard dict->dict actor call (no adapter needed)
    p = await validate_input(p)

    # @tool with non-standard signature: extracts p["city"] as argument,
    # stores result in p["weather"]. Compiler generates adapter_get_weather.
    p["weather"] = await get_weather(p["city"])

    # Sync @tool with non-standard signature: extracts p["user_name"],
    # stores result in p["greeting"]. Compiler generates adapter_format_greeting.
    p["greeting"] = format_greeting(p["user_name"])

    # Standard dict->dict actor call (no adapter needed)
    p = await compose_response(p)

    return p


# --- Handler stubs (deployed as separate AsyncActors) ---


@actor
async def validate_input(p: dict) -> dict:
    """Validate required fields are present in the payload."""
    return p


@actor
async def compose_response(p: dict) -> dict:
    """Compose the final response from weather data and greeting."""
    return p
