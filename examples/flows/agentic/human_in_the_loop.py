"""
Human-in-the-Loop - agent pauses for human approval at checkpoints.

The agent performs autonomous work but pauses at defined gates to request
human review before proceeding. The human can approve, reject, or modify
the agent's proposed action. This is essential for high-stakes decisions.

In Asya, the "approval gate" is an actor whose queue is consumed by a
human-facing UI (dashboard, Slack bot, email). The human's response is
sent as a new message that continues the flow.

Pattern: agent_work -> approval_gate -> if approved -> continue; elif rejected -> revise -> loop

ADK equivalent:
  - Deep Search: plan generated, then human approves before execution
  - https://github.com/google/adk-samples/tree/main/python/agents/deep-search
  - Order Processing: human approval for orders exceeding 100 units
  - https://github.com/google/adk-samples/tree/main/python/agents/order-processing
  - Product Catalog Ad Generation: human feedback at creative checkpoints
  - https://github.com/google/adk-samples/tree/main/python/agents/product-catalog-ad-generation

Framework references:
  - LangGraph Human-in-the-Loop with interrupt_before
    https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/
  - Mastra suspend/resume for human approval
    https://mastra.ai/docs/workflows/suspend-and-resume
  - Google Cloud: human oversight for agentic systems
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Deployment:
  - proposal_generator: LLM actor that produces a proposed action
  - approval_gate: actor whose queue is drained by a human-facing UI
  - executor: carries out the approved action
  - revision_agent: revises proposal based on human feedback
  - notifier: sends confirmation to the user

Payload contract:
  state["request"]        - user's original request
  state["proposal"]       - agent's proposed action
  state["approval"]       - human's decision ("approved"|"rejected"|"modified")
  state["human_feedback"] - human's notes or modifications
  state["result"]         - execution result

NOTE: The approval gate actor is special: it doesn't process the message
immediately. Instead, it holds the message until a human responds via
an external interface (web UI, Slack, email). The human's response is
written into the payload and the message is re-enqueued to continue
the flow. This requires the approval_gate actor to integrate with
a notification/response system outside of Asya.
"""


async def human_in_the_loop(state: dict) -> dict:
    state["attempt"] = 0

    while True:
        state["attempt"] += 1

        # Agent generates a proposal
        state = await proposal_generator(state)

        # Human review checkpoint
        state = await approval_gate(state)

        # Human approved: execute the action
        if state.get("approval") == "approved":
            state = await executor(state)
            break

        # Human modified: execute with modifications
        if state.get("approval") == "modified":
            state = await executor(state)
            break

        # Human rejected: revise and try again
        if state.get("approval") == "rejected":
            state = await revision_agent(state)

        # Safety: max revision attempts
        if state["attempt"] >= 3:
            state["result"] = "Max revision attempts reached"
            break

    # Notify user of the outcome
    state = await notifier(state)
    return state


# --- Handler stubs ---


async def proposal_generator(state: dict) -> dict:
    """LLM actor: generate a proposed action for human review.

    Reads state["request"] (and state["human_feedback"] on subsequent
    iterations). Produces state["proposal"] - a structured description
    of what the agent wants to do, with rationale.

    The proposal should be detailed enough for a human to make an
    informed approval decision.
    """
    return state


async def approval_gate(state: dict) -> dict:
    """Human interface actor: pause for human review.

    This actor is NOT an LLM. It integrates with a human-facing system:
    - Sends state["proposal"] to a dashboard, Slack, or email
    - Waits for human response (approval, rejection, or modification)
    - Sets state["approval"] and state["human_feedback"]

    Implementation options:
    - Web dashboard that reads from and writes to the actor's queue
    - Slack bot that presents the proposal and captures the response
    - Email-based approval with reply parsing

    The actor's queue will have a long message visibility timeout
    to accommodate human response time.
    """
    return state


async def executor(state: dict) -> dict:
    """Actor: carry out the approved action.

    Reads state["proposal"] (possibly modified by human feedback)
    and executes it. Sets state["result"] with the outcome.

    This is where the actual side effects happen (database changes,
    API calls, deployments, etc.).
    """
    return state


async def revision_agent(state: dict) -> dict:
    """LLM actor: revise proposal based on human feedback.

    Reads state["human_feedback"] and adjusts the approach. The
    revised proposal will go through the approval gate again on
    the next iteration.
    """
    return state


async def notifier(state: dict) -> dict:
    """Actor: send confirmation of the outcome to the user.

    Notifies the user that the action was completed (or that
    max attempts were reached). Uses email, Slack, or push
    notification depending on configuration.
    """
    return state
