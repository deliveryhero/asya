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
  - write_report: actor that produces the final report with citations

Payload contract:
  state["question"]       - the research question
  state["findings"]       - accumulated research findings
  state["gaps"]           - identified gaps (set by critic; empty = done)
  state["search_query"]  - current search query
  state["iteration"]      - loop counter
  state["quality_score"]  - quality assessment from critic (0-100)
"""


async def research_and_refine(state: dict) -> dict:
    state["iteration"] = 0
    state["search_query"] = state.get("question", "")

    while True:
        state["iteration"] += 1

        # Search: execute current queries, accumulate findings
        state = await researcher(state)

        # Critique: evaluate research quality, identify gaps
        state = await critic(state)

        # Exit: no gaps found or quality threshold met
        if not state.get("gaps") or state.get("quality_score", 0) >= 85:
            break

        # Refine: generate better search queries based on gaps
        state = await refine_query(state)

        # Safety: max iterations
        if state["iteration"] >= 5:
            break

    # Produce final report from accumulated findings
    state = await write_report(state)
    return state


# --- Handler stubs ---


async def researcher(state: dict) -> dict:
    """LLM actor with search tools: execute queries, extract findings.

    Uses web search, academic databases, or document retrieval to
    find information relevant to state["search_query"]. Appends
    results to state["findings"] with source citations.
    """
    search_query = state.get("search_query", "")
    findings = state.get("findings", [])
    iteration = state.get("iteration", 0)

    if iteration == 1:
        findings.append({
            "source": "Nature Quantum Information, 2026",
            "title": "Breakthrough in topological qubit stability",
            "summary": "Researchers achieved record coherence times using Majorana fermions in superconducting circuits.",
            "relevance": "high"
        })
        findings.append({
            "source": "arXiv:2601.12345",
            "title": "Scalable quantum error correction protocols",
            "summary": "New surface code implementations reduce overhead by 40%.",
            "relevance": "high"
        })
    elif iteration == 2:
        findings.append({
            "source": "IEEE Quantum Engineering, 2026",
            "title": "Commercial applications of quantum computing in finance",
            "summary": "Monte Carlo simulations for risk assessment show 100x speedup on current quantum processors.",
            "relevance": "medium"
        })
        findings.append({
            "source": "MIT Technology Review, 2026",
            "title": "Quantum advantage in drug discovery",
            "summary": "Pharmaceutical companies report successful protein folding predictions using quantum algorithms.",
            "relevance": "high"
        })
    elif iteration == 3:
        findings.append({
            "source": "Physical Review Letters, 2026",
            "title": "Hybrid quantum-classical architectures for near-term applications",
            "summary": "Variational quantum eigensolvers integrated with classical ML achieve state-of-the-art results in optimization.",
            "relevance": "high"
        })

    state["findings"] = findings
    return state


async def critic(state: dict) -> dict:
    """LLM actor: evaluate research quality and identify gaps.

    Reviews state["findings"] against state["question"]. Produces:
    - state["quality_score"]: 0-100 assessment
    - state["gaps"]: list of topics/angles not yet covered

    The critique is what drives the iterative refinement - if the
    critic finds no gaps, the loop terminates.
    """
    findings = state.get("findings", [])
    question = state.get("question", "")
    iteration = state.get("iteration", 0)

    if iteration == 1:
        state["quality_score"] = 45
        state["gaps"] = [
            "Missing information on commercial applications",
            "No coverage of practical deployment challenges",
            "Limited discussion of hybrid quantum-classical approaches"
        ]
    elif iteration == 2:
        state["quality_score"] = 70
        state["gaps"] = [
            "Need more detail on hybrid architectures",
            "Economic viability analysis missing"
        ]
    else:
        state["quality_score"] = 90
        state["gaps"] = []

    return state


async def refine_query(state: dict) -> dict:
    """LLM actor: produce improved search queries based on identified gaps.

    Reads state["gaps"] and generates new state["search_queries"] that
    target the missing information. May also reframe the original
    question to explore different angles.
    """
    gaps = state.get("gaps", [])
    iteration = state.get("iteration", 0)

    if iteration == 1:
        state["search_query"] = "quantum computing commercial applications finance drug discovery 2026"
    elif iteration == 2:
        state["search_query"] = "hybrid quantum-classical architectures variational algorithms practical deployment"
    else:
        state["search_query"] = state.get("question", "")

    return state


async def write_report(state: dict) -> dict:
    """LLM actor: synthesize findings into a structured report.

    Combines all state["findings"] into a coherent report with
    proper citations, organized by theme or chronology.
    """
    findings = state.get("findings", [])
    question = state.get("question", "")

    report = f"Research Report: {question}\n\n"
    report += f"Quality Score: {state.get('quality_score', 0)}/100\n"
    report += f"Total Sources: {len(findings)}\n\n"

    report += "Key Findings:\n\n"
    for i, finding in enumerate(findings, 1):
        report += f"{i}. {finding['title']}\n"
        report += f"   Source: {finding['source']}\n"
        report += f"   Summary: {finding['summary']}\n"
        report += f"   Relevance: {finding['relevance']}\n\n"

    report += "Conclusion: Quantum computing research in 2026 shows significant progress across hardware stability, error correction, and commercial applications. The field is transitioning from pure research to practical deployment in finance and pharmaceutical sectors."

    state["report"] = report
    return state
