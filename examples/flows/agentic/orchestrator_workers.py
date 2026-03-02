"""
Orchestrator-Workers - dynamic LLM-directed task delegation.

A central orchestrator LLM analyzes the request, decides which worker agent(s)
to invoke, collects their results, and decides whether to invoke more workers
or produce the final output. The orchestrator dynamically selects workers
at each step -- the dispatch path is NOT predetermined.

Differs from Routing (static classification) in that the orchestrator
maintains a loop and may invoke different workers across iterations.

Pattern: while True -> orchestrator decides -> if/elif dispatch to worker -> if done break

ADK equivalent:
  - Travel Concierge: root agent dispatches to 6 phase-specific sub-agents
  - https://github.com/google/adk-samples/tree/main/python/agents/travel-concierge
  - Data Science: root delegates to BigQuery, AlloyDB, BQML, Visualization
  - https://github.com/google/adk-samples/tree/main/python/agents/data-science
  - Plumber: main agent delegates to Dataflow, Dataproc, dBT, GitHub, Monitoring
  - https://github.com/google/adk-samples/tree/main/python/agents/plumber

Framework references:
  - Anthropic "Orchestrator-Workers" pattern
    https://www.anthropic.com/engineering/building-effective-agents
  - LangGraph Supervisor agent
    https://langchain-ai.github.io/langgraph/tutorials/multi_agent/agent_supervisor/
  - AutoGen SelectorGroupChat (LLM selects next speaker)
    https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/selector-group-chat.html
  - Google Cloud "Coordinator" pattern
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Deployment:
  - orchestrator: LLM actor that plans and dispatches (the "brain")
  - data_worker, analysis_worker, writing_worker: specialist LLM actors
  - synthesizer: LLM actor that produces final output from accumulated results

Payload contract:
  state["request"]        - user's original request
  state["next_action"]    - orchestrator's decision (set by orchestrator LLM)
  state["worker_results"] - accumulated results from workers
  state["is_complete"]    - whether the orchestrator is done

Note on control flow: The while loop, if/elif dispatch, and break are pure
state transformations -- they compile into router actors. Only the function
calls (orchestrator, data_worker, etc.) become real deployed actors.
"""


async def orchestrator_workers(state: dict) -> dict:
    state["iteration"] = 0
    state["worker_results"] = []

    while True:
        state["iteration"] += 1

        state = await orchestrator(state)

        if state.get("is_complete"):
            break

        if state.get("next_action") == "research":
            state = await data_worker(state)
        elif state.get("next_action") == "analyze":
            state = await analysis_worker(state)
        elif state.get("next_action") == "write":
            state = await writing_worker(state)

        if state["iteration"] >= 10:
            break

    state = await synthesizer(state)
    return state


# ---------------------------------------------------------------------------
# Actor stubs -- each becomes a separately deployed AsyncActor.
# Replace `...` with real LLM calls, tool use, or business logic.
# ---------------------------------------------------------------------------


async def orchestrator(state: dict) -> dict:
    """LLM actor: the "brain" that plans and dispatches.

    Reads:  state["request"], state["worker_results"]
    Writes: state["next_action"] ("research"|"analyze"|"write")
            state["is_complete"] (True when no more workers needed)

    This is the only actor that requires an LLM -- it examines all
    accumulated worker results and decides what to do next. The decision
    is non-deterministic, which is why this cannot be inlined into
    the flow DSL as a static conditional.
    """
    ...  # LLM call: given request + worker_results, decide next_action


async def data_worker(state: dict) -> dict:
    """LLM+tools actor: gather data and information.

    Reads:  state["request"]
    Writes: appends to state["worker_results"]

    Specialized in web search, database queries, and data retrieval.
    Has tool access (search APIs, databases, document stores).
    """
    ...  # LLM call with tools: search, retrieve, extract findings


async def analysis_worker(state: dict) -> dict:
    """LLM+tools actor: analyze data.

    Reads:  state["worker_results"] (previous findings)
    Writes: appends to state["worker_results"]

    Specialized in statistical analysis, pattern recognition, and
    computation. Has tool access (calculators, plotting, code execution).
    """
    ...  # LLM call with tools: analyze data, compute statistics


async def writing_worker(state: dict) -> dict:
    """LLM actor: produce written content.

    Reads:  state["worker_results"] (all findings + analyses)
    Writes: appends to state["worker_results"]

    Specialized in drafting reports, summaries, and communications.
    """
    ...  # LLM call: draft report/summary from accumulated results


async def synthesizer(state: dict) -> dict:
    """LLM actor: produce final output from accumulated worker results.

    Reads:  state["worker_results"]
    Writes: state["final_output"]

    Combines all worker contributions into a coherent final response.
    """
    ...  # LLM call: synthesize worker_results into final_output
