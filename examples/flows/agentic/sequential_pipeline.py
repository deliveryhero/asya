"""
Sequential Agent Pipeline - fixed chain of specialized agents.

The simplest multi-agent pattern: agents execute in a predetermined order,
each enriching the payload for the next. No branching, no loops — pure
linear data flow.

Pattern: agent_A -> agent_B -> agent_C -> agent_D

ADK equivalent:
  - ADK SequentialAgent: runs sub-agents in order within a single session
  - Financial Advisor: Data Analyst -> Trading Analyst -> Execution -> Risk
  - https://github.com/google/adk-samples/tree/main/python/agents/financial-advisor
  - Podcast Transcript: Topics -> Episode Planner -> Transcript Writer
  - https://github.com/google/adk-samples/tree/main/python/agents/podcast-transcript-agent
  - FOMC Research: 6 agents in strict sequence
  - https://github.com/google/adk-samples/tree/main/python/agents/fomc-research
  - Short Movie: Director -> Story -> Screenplay -> Storyboard -> Video
  - https://github.com/google/adk-samples/tree/main/python/agents/short-movie-agents

Framework references:
  - Anthropic "Prompt Chaining" pattern
    https://www.anthropic.com/engineering/building-effective-agents
  - CrewAI Sequential Process
    https://docs.crewai.com/concepts/crews#sequential-process
  - Google Cloud "Multi-agent (sequential)" pattern
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Deployment:
  Each agent is a separate AsyncActor. The start router sets
  route.next = [data_analyst, trading_analyst, execution_planner, risk_evaluator]
  and messages flow through the chain automatically.

Payload contract:
  state["topic"]           - investment topic to analyze
  state["market_data"]     - market research (set by data_analyst)
  state["strategies"]      - trading strategies (set by trading_analyst)
  state["exec_plan"]       - execution plan (set by execution_planner)
  state["risk_assessment"] - risk evaluation (set by risk_evaluator)
"""


async def sequential_pipeline(state: dict) -> dict:
    # Each agent enriches the payload with its analysis
    state = await data_analyst(state)
    state = await trading_analyst(state)
    state = await execution_planner(state)
    state = await risk_evaluator(state)
    return state


# --- Handler stubs ---


async def data_analyst(state: dict) -> dict:
    """LLM actor: research market data for the given topic.

    Uses web search and financial APIs to gather market data.
    Writes state["market_data"] with trends, prices, and news.
    """
    return state


async def trading_analyst(state: dict) -> dict:
    """LLM actor: generate trading strategies based on market data.

    Reads state["market_data"], produces state["strategies"] - a list
    of 5+ strategies with entry/exit points and rationale.
    """
    return state


async def execution_planner(state: dict) -> dict:
    """LLM actor: create implementation plan for chosen strategies.

    Reads state["strategies"], produces state["exec_plan"] with
    specific actions, timelines, and position sizes.
    """
    return state


async def risk_evaluator(state: dict) -> dict:
    """LLM actor: comprehensive risk assessment.

    Reads all prior state, produces state["risk_assessment"] covering
    market risk, concentration risk, liquidity risk, and recommended
    mitigations.
    """
    return state
