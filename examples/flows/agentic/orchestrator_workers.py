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
  - data_worker, analysis_worker, writing_worker: specialist actors
  - synthesizer: produces final output from accumulated results

Payload contract:
  state["request"]       - user's original request
  state["next_action"]   - orchestrator's decision (set by orchestrator)
  state["worker_results"] - accumulated results from workers
  state["is_complete"]   - whether the orchestrator is done
"""


async def orchestrator_workers(state: dict) -> dict:
    state["iteration"] = 0

    while True:
        state["iteration"] += 1

        # Orchestrator: analyze current state, decide next action
        state = await orchestrator(state)

        # Check if orchestrator decided we're done
        if state.get("is_complete"):
            break

        # Dispatch to the worker chosen by orchestrator
        if state.get("next_action") == "research":
            state = await data_worker(state)
        elif state.get("next_action") == "analyze":
            state = await analysis_worker(state)
        elif state.get("next_action") == "write":
            state = await writing_worker(state)
        else:
            # Unknown action - let orchestrator reconsider
            state["next_action"] = "unknown"

        # Safety: max iterations
        if state["iteration"] >= 10:
            state["is_complete"] = True
            break

    # Synthesize final output from all worker results
    state = await synthesizer(state)
    return state


# --- Handler stubs ---


async def orchestrator(state: dict) -> dict:
    """LLM actor: the "brain" that plans and dispatches.

    Receives state["request"] and state["worker_results"]. Decides:
    - state["next_action"]: which worker to invoke ("research"|"analyze"|"write")
    - state["is_complete"]: True if no more workers needed

    The orchestrator sees ALL accumulated worker results and uses them
    to decide what to do next. This is what makes it dynamic -- the same
    request might take different paths depending on intermediate results.
    """
    request = state["request"]
    worker_results = state.get("worker_results", [])
    iteration = state.get("iteration", 0)

    if "worker_results" not in state:
        state["worker_results"] = []

    if iteration == 1:
        state["next_action"] = "research"
        state["is_complete"] = False
    elif iteration == 2:
        state["next_action"] = "analyze"
        state["is_complete"] = False
    elif iteration == 3:
        state["next_action"] = "write"
        state["is_complete"] = False
    else:
        state["next_action"] = None
        state["is_complete"] = True

    return state


async def data_worker(state: dict) -> dict:
    """LLM actor with search tools: gather data and information.

    Specialized in web search, database queries, and data retrieval.
    Appends its findings to state["worker_results"].
    """
    request = state["request"]

    findings = {
        "worker": "data_worker",
        "findings": f"Research results for '{request}': Found 47 relevant sources, 12 key statistics, and 5 primary data points from authoritative databases."
    }

    state["worker_results"].append(findings)
    return state


async def analysis_worker(state: dict) -> dict:
    """LLM actor with computation tools: analyze data.

    Specialized in data analysis, statistical computation, and
    pattern recognition. Appends its analysis to state["worker_results"].
    """
    worker_results = state["worker_results"]

    analysis = {
        "worker": "analysis_worker",
        "analysis": f"Statistical analysis complete: 3 major trends identified, correlation coefficient 0.87, p-value < 0.01. Key pattern: exponential growth in Q3-Q4."
    }

    state["worker_results"].append(analysis)
    return state


async def writing_worker(state: dict) -> dict:
    """LLM actor: produce written content.

    Specialized in drafting reports, summaries, and communications.
    Appends its output to state["worker_results"].
    """
    worker_results = state["worker_results"]

    written_content = {
        "worker": "writing_worker",
        "content": "Executive Summary: Based on comprehensive research and analysis, the data reveals significant trends with high statistical confidence. The findings support strategic recommendations for Q1 2026 planning."
    }

    state["worker_results"].append(written_content)
    return state


async def synthesizer(state: dict) -> dict:
    """LLM actor: produce final output from accumulated worker results.

    Reads state["worker_results"] and combines them into a coherent
    final response for the user.
    """
    worker_results = state["worker_results"]

    combined_sections = []
    for result in worker_results:
        if "findings" in result:
            combined_sections.append(f"Research: {result['findings']}")
        elif "analysis" in result:
            combined_sections.append(f"Analysis: {result['analysis']}")
        elif "content" in result:
            combined_sections.append(f"Summary: {result['content']}")

    state["final_output"] = " | ".join(combined_sections)
    return state
