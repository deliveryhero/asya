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
    message = state.get("message", "").lower()

    if any(word in message for word in ["invoice", "payment", "charge", "refund", "billing", "bill"]):
        state["category"] = "billing"
    elif any(word in message for word in ["error", "bug", "crash", "broken", "not working", "technical"]):
        state["category"] = "technical"
    elif any(word in message for word in ["password", "account", "profile", "login", "subscription"]):
        state["category"] = "account"
    else:
        state["category"] = "general"

    return state


async def billing_agent(state: dict) -> dict:
    """LLM actor: handle billing inquiries.

    Has access to billing system tools (invoice lookup, payment status,
    refund processing). Writes state["resolution"].
    """
    message = state.get("message", "")
    category = state.get("category", "unknown")

    state["resolution"] = (
        f"I've reviewed your billing inquiry. Your last invoice (INV-2026-0847) "
        f"for $127.50 was processed on February 15, 2026. Payment status shows "
        f"successful charge to card ending in 4892. If you need a detailed "
        f"breakdown or have concerns about specific charges, I can provide an "
        f"itemized statement or initiate a refund request within 30 days of "
        f"the transaction date."
    )
    return state


async def technical_agent(state: dict) -> dict:
    """LLM actor: handle technical support.

    Has access to documentation search, bug tracker, and system status
    tools. Writes state["resolution"].
    """
    message = state.get("message", "")

    state["resolution"] = (
        f"I've identified the issue you're experiencing. This appears to be "
        f"related to the API timeout configuration in version 2.4.1. Our system "
        f"status shows all services operational, but we have a known issue "
        f"(TECH-3892) affecting connection pooling under high load. "
        f"Workaround: increase timeout to 30 seconds and enable retry logic. "
        f"A permanent fix is scheduled for release 2.4.2 on March 15. "
        f"You can track progress at status.example.com/TECH-3892"
    )
    return state


async def account_agent(state: dict) -> dict:
    """LLM actor: handle account management.

    Has access to account CRUD tools (profile update, password reset,
    subscription changes). Writes state["resolution"].
    """
    message = state.get("message", "")

    state["resolution"] = (
        f"I can help you with your account management request. Your account "
        f"(user_id: USR-88492) is currently on the Professional plan with "
        f"renewal date March 28, 2026. I've sent a password reset link to "
        f"your registered email (j****n@example.com). The link expires in "
        f"60 minutes. If you need to update your profile information or change "
        f"your subscription tier, I can process that immediately with your "
        f"confirmation. Current subscription options: Basic ($29/mo), "
        f"Professional ($79/mo), Enterprise (custom pricing)."
    )
    return state


async def general_agent(state: dict) -> dict:
    """LLM actor: handle uncategorized or general inquiries.

    Fallback handler with broad knowledge but fewer specialized tools.
    Writes state["resolution"].
    """
    message = state.get("message", "")

    state["resolution"] = (
        f"Thank you for reaching out. I'd be happy to help with your inquiry. "
        f"Our service offers comprehensive solutions for project management, "
        f"team collaboration, and workflow automation. Key features include: "
        f"real-time collaboration (up to 50 users), 99.9% uptime SLA, "
        f"integrations with 200+ tools, and 24/7 support. "
        f"For specific questions about features, pricing, or implementation, "
        f"I can connect you with a specialist or provide documentation links. "
        f"What aspect would you like to explore further?"
    )
    return state


async def format_reply(state: dict) -> dict:
    """Actor: format the resolution into a user-facing response.

    Applies consistent formatting, adds relevant links, and ensures
    the response meets quality standards regardless of which
    specialist handled it.
    """
    resolution = state.get("resolution", "")
    category = state.get("category", "general")

    category_labels = {
        "billing": "Billing Support",
        "technical": "Technical Support",
        "account": "Account Management",
        "general": "Customer Service",
    }

    state["formatted_reply"] = (
        f"--- {category_labels.get(category, 'Support')} ---\n\n"
        f"{resolution}\n\n"
        f"---\n"
        f"Need more help? Visit help.example.com or reply to this message.\n"
        f"Reference ID: REQ-{category.upper()[:4]}-{hash(resolution) % 100000:05d}\n"
        f"Response time: <1 minute | Category: {category}"
    )
    return state
