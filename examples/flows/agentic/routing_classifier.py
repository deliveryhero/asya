"""
Routing Classifier - classify input, dispatch to specialized handler.

A classification step examines the input and directs it to a specialized
processing path. Each path has different actors optimized for that
category. After processing, paths converge for unified post-processing.

Pattern: classifier -> if/elif/else on category -> specialized handler -> merge

ADK equivalent:
  - Brand Search Optimization: Router Agent dispatches to Data Retrieval
    or Search Results agents based on task type
  - https://github.com/google/adk-samples/tree/main/python/agents/brand-search-optimization
  - Travel Concierge: root agent routes to phase-specific sub-agents
  - https://github.com/google/adk-samples/tree/main/python/agents/travel-concierge

Framework references:
  - Anthropic "Routing" workflow pattern
    https://www.anthropic.com/engineering/building-effective-agents
  - LangGraph conditional_edges for routing
    https://langchain-ai.github.io/langgraph/how-tos/branching/
  - Google Cloud "Single agent" with routing logic
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Deployment:
  - classifier: lightweight LLM or ML model that categorizes requests
  - billing_agent, technical_agent, account_agent: domain specialists
  - general_agent: fallback for uncategorized requests
  - format_reply: unified response formatting

Payload contract:
  state["message"]    - user's request
  state["category"]   - classification result (billing|technical|account|general)
  state["resolution"] - the specialized agent's response
"""


async def routing_classifier(state: dict) -> dict:
    # Step 1: Classify the incoming request
    state = await classifier(state)

    # Step 2: Route to specialized handler based on category
    if state.get("category") == "billing":
        state = await billing_agent(state)
    elif state.get("category") == "technical":
        state = await technical_agent(state)
    elif state.get("category") == "account":
        state = await account_agent(state)
    else:
        state = await general_agent(state)

    # Step 3: Unified post-processing (all paths converge)
    state = await format_reply(state)
    return state


# --- Handler stubs ---


async def classifier(state: dict) -> dict:
    """LLM/ML actor: classify request into a category.

    Reads state["message"], sets state["category"] to one of:
    "billing", "technical", "account", or "general".

    Can be a lightweight model (Gemini Flash, Haiku) or even a
    traditional ML classifier for cost efficiency.
    """
    return state


async def billing_agent(state: dict) -> dict:
    """LLM actor: handle billing inquiries.

    Has access to billing system tools (invoice lookup, payment status,
    refund processing). Writes state["resolution"].
    """
    return state


async def technical_agent(state: dict) -> dict:
    """LLM actor: handle technical support.

    Has access to documentation search, bug tracker, and system status
    tools. Writes state["resolution"].
    """
    return state


async def account_agent(state: dict) -> dict:
    """LLM actor: handle account management.

    Has access to account CRUD tools (profile update, password reset,
    subscription changes). Writes state["resolution"].
    """
    return state


async def general_agent(state: dict) -> dict:
    """LLM actor: handle uncategorized or general inquiries.

    Fallback handler with broad knowledge but fewer specialized tools.
    Writes state["resolution"].
    """
    return state


async def format_reply(state: dict) -> dict:
    """Actor: format the resolution into a user-facing response.

    Applies consistent formatting, adds relevant links, and ensures
    the response meets quality standards regardless of which
    specialist handled it.
    """
    return state
