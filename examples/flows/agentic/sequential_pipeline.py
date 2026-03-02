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
    topic = state.get("topic", "unknown")
    state["market_data"] = {
        "topic": topic,
        "trends": [
            {"sector": "technology", "direction": "bullish", "momentum": 0.72},
            {"sector": "energy", "direction": "bearish", "momentum": -0.45},
            {"sector": "healthcare", "direction": "neutral", "momentum": 0.05},
        ],
        "prices": {
            "current": 142.35,
            "previous_close": 139.80,
            "52_week_high": 158.90,
            "52_week_low": 118.25,
        },
        "news": [
            "Quarterly earnings exceeded analyst expectations by 12%",
            "New regulatory framework announced affecting sector operations",
            "Major institutional investor increased stake by 8.5%",
        ],
    }
    return state


async def trading_analyst(state: dict) -> dict:
    """LLM actor: generate trading strategies based on market data.

    Reads state["market_data"], produces state["strategies"] - a list
    of 5+ strategies with entry/exit points and rationale.
    """
    market_data = state.get("market_data", {})
    current_price = market_data.get("prices", {}).get("current", 0)

    state["strategies"] = [
        {
            "name": "Momentum Breakout",
            "entry": current_price * 1.03,
            "exit": current_price * 1.15,
            "rationale": "Positive earnings momentum suggests continuation pattern",
        },
        {
            "name": "Support Bounce",
            "entry": current_price * 0.97,
            "exit": current_price * 1.08,
            "rationale": "Recent institutional buying provides strong support level",
        },
        {
            "name": "Sector Rotation",
            "entry": current_price * 0.99,
            "exit": current_price * 1.12,
            "rationale": "Technology sector bullish trend indicates sector-wide gains",
        },
        {
            "name": "Earnings Run-up",
            "entry": current_price * 1.01,
            "exit": current_price * 1.09,
            "rationale": "Pre-earnings positioning based on historical patterns",
        },
        {
            "name": "Mean Reversion",
            "entry": current_price * 0.95,
            "exit": current_price * 1.05,
            "rationale": "Price deviation from 50-day moving average presents opportunity",
        },
    ]
    return state


async def execution_planner(state: dict) -> dict:
    """LLM actor: create implementation plan for chosen strategies.

    Reads state["strategies"], produces state["exec_plan"] with
    specific actions, timelines, and position sizes.
    """
    strategies = state.get("strategies", [])

    state["exec_plan"] = {
        "selected_strategies": [strategies[0]["name"], strategies[2]["name"]] if strategies else [],
        "actions": [
            {
                "action": "Place limit order",
                "strategy": strategies[0]["name"] if strategies else "unknown",
                "price": strategies[0]["entry"] if strategies else 0,
                "quantity": 500,
                "timing": "Market open, Day 1",
            },
            {
                "action": "Set stop-loss",
                "strategy": strategies[0]["name"] if strategies else "unknown",
                "price": strategies[0]["entry"] * 0.95 if strategies else 0,
                "quantity": 500,
                "timing": "Immediately after fill",
            },
            {
                "action": "Scale into position",
                "strategy": strategies[2]["name"] if len(strategies) > 2 else "unknown",
                "price": strategies[2]["entry"] if len(strategies) > 2 else 0,
                "quantity": 300,
                "timing": "Day 2-3, on pullback",
            },
        ],
        "timeline": "3-day execution window, review on Day 4",
        "total_capital_allocated": 115000,
        "max_position_size": 800,
    }
    return state


async def risk_evaluator(state: dict) -> dict:
    """LLM actor: comprehensive risk assessment.

    Reads all prior state, produces state["risk_assessment"] covering
    market risk, concentration risk, liquidity risk, and recommended
    mitigations.
    """
    market_data = state.get("market_data", {})
    strategies = state.get("strategies", [])
    exec_plan = state.get("exec_plan", {})

    state["risk_assessment"] = {
        "market_risk": {
            "level": "moderate",
            "factors": [
                "Regulatory uncertainty from recent announcements",
                "Sector volatility elevated by 23% above historical average",
            ],
        },
        "concentration_risk": {
            "level": "low",
            "analysis": f"Position size {exec_plan.get('max_position_size', 0)} represents 7.8% of portfolio",
        },
        "liquidity_risk": {
            "level": "low",
            "avg_daily_volume": 8500000,
            "position_to_volume_ratio": 0.009,
        },
        "strategy_risk": {
            "correlation": f"{len(strategies)} strategies deployed with 0.62 correlation",
            "diversification_score": 0.74,
        },
        "mitigations": [
            "Implement trailing stop-loss at 8% below entry",
            "Reduce position size by 20% if sector volatility exceeds 30%",
            "Set hard exit if regulatory news turns materially negative",
            "Monitor institutional flow data for early exit signals",
        ],
        "overall_risk_rating": "acceptable",
    }
    return state
