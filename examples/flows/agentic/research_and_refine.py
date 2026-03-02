"""
Research-and-Refine - iterative search-critique-deepen loop.

Unlike ReAct (single LLM decides everything), this pattern uses SEPARATE
search and critique actors in each iteration. The critique actor identifies
gaps in the research, and the search is refined until quality is sufficient.

Pattern: while True -> search -> critique -> if gaps -> refine query -> loop; else break

ADK equivalent:
  - Deep Search: iterative research with autonomous gap detection
  - https://github.com/google/adk-samples/tree/main/python/agents/deep-search
  - Academic Research: 3 agents (analysis, citation discovery, future directions)
  - https://github.com/google/adk-samples/tree/main/python/agents/academic-research

Framework references:
  - LangGraph Adaptive RAG / Self-RAG with reflection
    https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_adaptive_rag/
  - LangGraph Corrective RAG (CRAG)
    https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_crag/

Deployment:
  - researcher: LLM actor with search tools
  - critic: LLM actor that evaluates research quality and identifies gaps
  - refine_query: LLM actor that produces improved search queries
  - write_report: LLM actor that produces the final report with citations

Payload contract:
  state["question"]       - the research question
  state["findings"]       - accumulated research findings
  state["gaps"]           - identified gaps (set by critic; empty = done)
  state["search_query"]   - current search query
  state["iteration"]      - loop counter
  state["quality_score"]  - quality assessment from critic (0-100)

Note on control flow: The while loop, quality threshold check, and break
are pure state transformations -- they compile into router actors. Only the
function calls (researcher, critic, etc.) become real deployed actors.
"""


async def research_and_refine(state: dict) -> dict:
    state["iteration"] = 0
    state["search_query"] = state.get("question", "")

    while True:
        state["iteration"] += 1
        state = await researcher(state)
        state = await critic(state)

        if not state.get("gaps") or state.get("quality_score", 0) >= 85:
            break

        state = await refine_query(state)
        if state["iteration"] >= 5:
            break

    state = await write_report(state)
    return state


# ---------------------------------------------------------------------------
# Actor stubs -- each becomes a separately deployed AsyncActor.
# Replace `...` with real LLM calls, tool use, or business logic.
# ---------------------------------------------------------------------------


async def researcher(state: dict) -> dict:
    """LLM+tools actor: execute queries, extract findings.

    Reads:  state["search_query"]
    Writes: appends to state["findings"] (list of {source, title, summary})

    Uses web search, academic databases, or document retrieval to find
    information. Each finding should include source citations.
    """
    ...  # LLM call with search tools: query, extract, cite


async def critic(state: dict) -> dict:
    """LLM actor: evaluate research quality and identify gaps.

    Reads:  state["findings"], state["question"]
    Writes: state["quality_score"] (0-100)
            state["gaps"] (list of missing topics; empty = done)

    The critique drives the iterative loop -- if the critic finds no
    gaps or quality_score >= 85, the loop terminates. This actor's
    judgment determines how many iterations the flow runs.
    """
    ...  # LLM call: assess coverage, score quality, list gaps


async def refine_query(state: dict) -> dict:
    """LLM actor: produce improved search queries based on gaps.

    Reads:  state["gaps"], state["question"]
    Writes: state["search_query"]

    Generates new search queries that target the missing information
    identified by the critic. May reframe the original question to
    explore different angles.
    """
    ...  # LLM call: gaps -> refined search queries


async def write_report(state: dict) -> dict:
    """LLM actor: synthesize findings into a structured report.

    Reads:  state["findings"], state["question"], state["quality_score"]
    Writes: state["report"]

    Combines all accumulated findings into a coherent report with
    proper citations, organized by theme.
    """
    ...  # LLM call: findings -> structured report with citations
