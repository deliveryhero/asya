"""
Hierarchical Delegation - multi-level tree of agents.

Agents are organized in a hierarchy: a root agent decomposes the task
into major subtasks and delegates to mid-level agents. Each mid-level
agent may further delegate to leaf-level specialists. Results propagate
back up the tree.

Differs from Orchestrator-Workers (flat, single-level delegation) in that
this pattern has MULTIPLE LEVELS of decomposition. Each mid-level agent
is itself an orchestrator for its domain.

Pattern: root -> if/elif -> mid_level_A (-> leaf specialists) | mid_level_B (-> leaf specialists)

ADK equivalent:
  - Plumber: root -> 6 sub-agents, each with their own tool sets
  - https://github.com/google/adk-samples/tree/main/python/agents/plumber
  - Data Science: root -> BigQuery Agent (NL2SQL sub-tools), AlloyDB Agent
    (MCP sub-tools), BQML Agent (ML sub-tools), Visualization Agent
  - https://github.com/google/adk-samples/tree/main/python/agents/data-science
  - MLE-STAR: hierarchical refinement with specialized sub-agents
  - https://github.com/google/adk-samples/tree/main/python/agents/mle-star

Framework references:
  - LangGraph Hierarchical Agent Teams
    https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/
  - CrewAI Hierarchical Process
    https://docs.crewai.com/concepts/crews#hierarchical-process
  - Google Cloud "Coordinator" pattern (multi-level variant)
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Deployment:
  - root_agent: top-level LLM that categorizes and delegates
  - data_team_lead, content_team_lead: mid-level orchestrators
  - sql_specialist, api_specialist, editor, writer: leaf workers
  - final_assembler: combines all team outputs

Payload contract:
  state["project"]         - the project/request description
  state["domain"]          - primary domain (set by root_agent)
  state["team_output"]     - output from the delegated team
  state["final_delivery"]  - assembled final output

NOTE: Since compiled flows have the same signature as actors (dict -> dict),
a flow can call another flow via `state = await sub_flow(state)`. The
sub-flow's start router is just another actor. This example flattens the
hierarchy inline for clarity, but in production each team could be its
own compiled flow deployed as an independent actor network.
"""


async def hierarchical_delegation(state: dict) -> dict:
    # Root agent: analyze and categorize the project
    state = await root_agent(state)

    # Delegate to the appropriate team based on domain
    if state.get("domain") == "data":
        # Data team: mid-level lead coordinates specialists
        state = await data_team_lead(state)

        if state.get("subtask") == "sql":
            state = await sql_specialist(state)
        elif state.get("subtask") == "api":
            state = await api_specialist(state)
        else:
            state = await data_generalist(state)

    elif state.get("domain") == "content":
        # Content team: mid-level lead coordinates specialists
        state = await content_team_lead(state)

        if state.get("subtask") == "write":
            state = await writer(state)
        elif state.get("subtask") == "edit":
            state = await editor(state)
        else:
            state = await content_generalist(state)

    else:
        # Fallback: handle directly
        state = await generalist(state)

    # Assemble final output from team results
    state = await final_assembler(state)
    return state


# --- Handler stubs ---


async def root_agent(state: dict) -> dict:
    """LLM actor: top-level decomposition and delegation.

    Analyzes state["project"], determines the primary domain ("data"|
    "content"|other), and sets state["domain"] for routing.
    """
    project = state.get("project", "")
    project_lower = project.lower()

    if any(kw in project_lower for kw in ["sql", "query", "database", "analytics", "api", "fetch"]):
        state["domain"] = "data"
    elif any(kw in project_lower for kw in ["write", "article", "blog", "edit", "copy", "content"]):
        state["domain"] = "content"
    else:
        state["domain"] = "other"

    return state


async def data_team_lead(state: dict) -> dict:
    """LLM actor: mid-level data team orchestrator.

    Receives data-related tasks, further decomposes into subtasks
    ("sql"|"api"|other), sets state["subtask"] for leaf routing.
    """
    project = state.get("project", "")
    project_lower = project.lower()

    if any(kw in project_lower for kw in ["sql", "query", "database", "select", "schema"]):
        state["subtask"] = "sql"
    elif any(kw in project_lower for kw in ["api", "rest", "fetch", "endpoint", "http"]):
        state["subtask"] = "api"
    else:
        state["subtask"] = "other"

    return state


async def sql_specialist(state: dict) -> dict:
    """LLM actor: SQL query generation and execution.

    Leaf-level specialist with database tools. Handles NL2SQL,
    schema inspection, query optimization.
    """
    state["team_output"] = {
        "query": "SELECT customer_id, SUM(total) AS revenue FROM orders WHERE created_at >= '2024-01-01' GROUP BY customer_id ORDER BY revenue DESC LIMIT 10",
        "results": [
            {"customer_id": 1245, "revenue": 125430.50},
            {"customer_id": 8921, "revenue": 98234.20},
            {"customer_id": 3456, "revenue": 87120.00}
        ],
        "schema_inspected": ["orders", "customers"],
        "execution_time_ms": 142
    }
    return state


async def api_specialist(state: dict) -> dict:
    """LLM actor: API integration specialist.

    Leaf-level specialist with HTTP/REST tools. Handles API calls,
    data transformation, pagination.
    """
    state["team_output"] = {
        "endpoint": "https://api.example.com/v2/analytics/revenue",
        "method": "GET",
        "status_code": 200,
        "data": {
            "total_revenue": 1250000.00,
            "period": "2024-Q1",
            "breakdown": [
                {"category": "subscriptions", "amount": 850000},
                {"category": "one_time", "amount": 400000}
            ]
        },
        "pagination": {"page": 1, "total_pages": 1},
        "cache_hit": False
    }
    return state


async def data_generalist(state: dict) -> dict:
    """LLM actor: general data tasks.

    Fallback for data tasks that don't fit sql or api specialization.
    """
    state["team_output"] = {
        "analysis_type": "exploratory",
        "findings": [
            "Data quality assessment completed",
            "Identified 3 key trends in user behavior",
            "Recommended additional data collection for Q2"
        ],
        "visualizations": ["correlation_matrix.png", "trend_plot.png"],
        "confidence": "medium"
    }
    return state


async def content_team_lead(state: dict) -> dict:
    """LLM actor: mid-level content team orchestrator.

    Receives content-related tasks, further decomposes into subtasks
    ("write"|"edit"|other), sets state["subtask"] for leaf routing.
    """
    project = state.get("project", "")
    project_lower = project.lower()

    if any(kw in project_lower for kw in ["write", "draft", "create", "compose", "article"]):
        state["subtask"] = "write"
    elif any(kw in project_lower for kw in ["edit", "review", "polish", "improve", "revise"]):
        state["subtask"] = "edit"
    else:
        state["subtask"] = "other"

    return state


async def writer(state: dict) -> dict:
    """LLM actor: content creation specialist.

    Leaf-level specialist for drafting articles, reports, copy.
    """
    state["team_output"] = {
        "content_type": "blog_post",
        "title": "The Future of Distributed AI Systems",
        "word_count": 1850,
        "draft": "In the rapidly evolving landscape of artificial intelligence, distributed systems are becoming increasingly important...",
        "sections": ["Introduction", "Core Concepts", "Real-world Applications", "Conclusion"],
        "seo_keywords": ["AI systems", "distributed computing", "machine learning"],
        "readability_score": 68
    }
    return state


async def editor(state: dict) -> dict:
    """LLM actor: content editing specialist.

    Leaf-level specialist for reviewing, improving, and polishing text.
    """
    state["team_output"] = {
        "original_word_count": 1850,
        "edited_word_count": 1720,
        "changes_made": [
            "Removed redundant phrases in paragraphs 2-4",
            "Strengthened topic sentences across all sections",
            "Improved flow between Core Concepts and Applications",
            "Fixed 12 grammar issues and 3 style inconsistencies"
        ],
        "readability_improvement": {"before": 68, "after": 74},
        "tone": "professional yet accessible",
        "final_draft": "In the rapidly evolving landscape of artificial intelligence, distributed systems have become critical..."
    }
    return state


async def content_generalist(state: dict) -> dict:
    """LLM actor: general content tasks.

    Fallback for content tasks that don't fit write or edit specialization.
    """
    state["team_output"] = {
        "task_type": "content_strategy",
        "recommendations": [
            "Develop content calendar for Q2 2024",
            "Focus on technical deep-dive pieces",
            "Target developer and architect personas"
        ],
        "competitive_analysis": "Analyzed 5 competitor blogs",
        "content_gaps": ["case studies", "implementation guides"],
        "next_steps": ["Schedule editorial planning meeting", "Draft content brief templates"]
    }
    return state


async def generalist(state: dict) -> dict:
    """LLM actor: handles tasks that don't fit any team.

    Fallback handler for uncategorized or cross-domain requests.
    """
    state["team_output"] = {
        "approach": "general_problem_solving",
        "assessment": "Task requires cross-domain expertise",
        "steps_taken": [
            "Analyzed requirements from multiple angles",
            "Identified potential solutions",
            "Evaluated trade-offs"
        ],
        "recommendation": "Consider breaking into smaller domain-specific subtasks",
        "confidence": "low_to_medium"
    }
    return state


async def final_assembler(state: dict) -> dict:
    """Actor: assemble final output from team results.

    Combines state["team_output"] with any formatting or
    cross-referencing needed for the final delivery.
    """
    team_output = state.get("team_output", {})
    domain = state.get("domain", "unknown")

    state["final_delivery"] = {
        "project": state.get("project", ""),
        "domain": domain,
        "team_results": team_output,
        "summary": f"Completed {domain} domain task with team collaboration",
        "completion_timestamp": "2024-03-15T14:32:18Z",
        "quality_score": 0.92
    }
    return state
