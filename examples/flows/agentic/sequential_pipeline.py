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

Typed actors:
  Actor handlers return dataclasses directly — the Asya runtime serializes
  them automatically. No .model_dump() or manual dict conversion needed.
  Works the same way with pydantic BaseModel, NamedTuple, or any duck-typed
  object that implements model_dump() or __dataclass_fields__.

Payload contract:
  state["topic"]           - investment topic to analyze
  state["market_data"]     - MarketData (set by data_analyst)
  state["strategies"]      - list[TradingStrategy] (set by trading_analyst)
  state["exec_plan"]       - ExecutionPlan (set by execution_planner)
  state["risk_assessment"] - RiskAssessment (set by risk_evaluator)
"""

from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Typed result models for each actor
# (pydantic BaseModel works identically — swap @dataclass for BaseModel)
# ---------------------------------------------------------------------------


@dataclass
class SectorTrend:
    sector: str
    direction: str
    momentum: float


@dataclass
class MarketData:
    topic: str
    trends: List[SectorTrend]
    current_price: float
    previous_close: float
    news: List[str]


@dataclass
class TradingStrategy:
    name: str
    entry: float
    exit: float
    rationale: str


@dataclass
class ExecutionAction:
    action: str
    strategy: str
    price: float
    quantity: int
    timing: str


@dataclass
class ExecutionPlan:
    selected_strategies: List[str]
    actions: List[ExecutionAction]
    timeline: str
    total_capital_allocated: int
    max_position_size: int


@dataclass
class RiskAssessment:
    market_risk_level: str
    concentration_risk_level: str
    liquidity_risk_level: str
    overall_rating: str
    mitigations: List[str]


# ---------------------------------------------------------------------------
# Flow definition
# ---------------------------------------------------------------------------


async def sequential_pipeline(state: dict) -> dict:
    # Each actor returns a typed result — stored under a named key in state.
    # The runtime serializes dataclasses automatically when forwarding to the
    # next actor in the chain.
    state["market_data"] = await data_analyst(state)
    state["strategies"] = await trading_analyst(state)
    state["exec_plan"] = await execution_planner(state)
    state["risk_assessment"] = await risk_evaluator(state)
    return state


# ---------------------------------------------------------------------------
# Handler stubs
# ---------------------------------------------------------------------------


async def data_analyst(payload: dict) -> MarketData:
    """LLM actor: research market data for the given topic.

    Uses web search and financial APIs to gather market data.
    Returns a MarketData object — the runtime serializes it to JSON automatically.
    """
    topic = payload.get("topic", "unknown")
    return MarketData(
        topic=topic,
        trends=[
            SectorTrend(sector="technology", direction="bullish", momentum=0.72),
            SectorTrend(sector="energy", direction="bearish", momentum=-0.45),
            SectorTrend(sector="healthcare", direction="neutral", momentum=0.05),
        ],
        current_price=142.35,
        previous_close=139.80,
        news=[
            "Quarterly earnings exceeded analyst expectations by 12%",
            "New regulatory framework announced affecting sector operations",
            "Major institutional investor increased stake by 8.5%",
        ],
    )


async def trading_analyst(payload: dict) -> List[TradingStrategy]:
    """LLM actor: generate trading strategies based on market data.

    Reads payload["market_data"], returns a list of TradingStrategy objects.
    Lists of dataclasses serialize automatically — each element is converted
    via dataclasses.asdict().
    """
    market_data = payload.get("market_data", {})
    price = market_data.get("current_price", 0) if isinstance(market_data, dict) else getattr(market_data, "current_price", 0)

    return [
        TradingStrategy(
            name="Momentum Breakout",
            entry=price * 1.03,
            exit=price * 1.15,
            rationale="Positive earnings momentum suggests continuation pattern",
        ),
        TradingStrategy(
            name="Support Bounce",
            entry=price * 0.97,
            exit=price * 1.08,
            rationale="Recent institutional buying provides strong support level",
        ),
        TradingStrategy(
            name="Sector Rotation",
            entry=price * 0.99,
            exit=price * 1.12,
            rationale="Technology sector bullish trend indicates sector-wide gains",
        ),
        TradingStrategy(
            name="Earnings Run-up",
            entry=price * 1.01,
            exit=price * 1.09,
            rationale="Pre-earnings positioning based on historical patterns",
        ),
        TradingStrategy(
            name="Mean Reversion",
            entry=price * 0.95,
            exit=price * 1.05,
            rationale="Price deviation from 50-day moving average presents opportunity",
        ),
    ]


async def execution_planner(payload: dict) -> ExecutionPlan:
    """LLM actor: create implementation plan for chosen strategies.

    Reads payload["strategies"], returns a typed ExecutionPlan.
    Nested dataclasses (ExecutionAction inside ExecutionPlan) are
    recursively serialized by dataclasses.asdict().
    """
    strategies = payload.get("strategies", [])

    def _name(s):
        return s["name"] if isinstance(s, dict) else s.name

    def _entry(s):
        return s["entry"] if isinstance(s, dict) else s.entry

    first = strategies[0] if strategies else None
    third = strategies[2] if len(strategies) > 2 else None

    return ExecutionPlan(
        selected_strategies=[_name(s) for s in strategies[:2]],
        actions=[
            ExecutionAction(
                action="Place limit order",
                strategy=_name(first) if first else "unknown",
                price=_entry(first) if first else 0,
                quantity=500,
                timing="Market open, Day 1",
            ),
            ExecutionAction(
                action="Set stop-loss",
                strategy=_name(first) if first else "unknown",
                price=_entry(first) * 0.95 if first else 0,
                quantity=500,
                timing="Immediately after fill",
            ),
            ExecutionAction(
                action="Scale into position",
                strategy=_name(third) if third else "unknown",
                price=_entry(third) if third else 0,
                quantity=300,
                timing="Day 2-3, on pullback",
            ),
        ],
        timeline="3-day execution window, review on Day 4",
        total_capital_allocated=115000,
        max_position_size=800,
    )


async def risk_evaluator(payload: dict) -> RiskAssessment:
    """LLM actor: comprehensive risk assessment.

    Reads all prior state, returns a typed RiskAssessment.
    """
    strategies = payload.get("strategies", [])
    exec_plan = payload.get("exec_plan", {})
    max_pos = exec_plan.get("max_position_size", 0) if isinstance(exec_plan, dict) else getattr(exec_plan, "max_position_size", 0)

    return RiskAssessment(
        market_risk_level="moderate",
        concentration_risk_level="low",
        liquidity_risk_level="low",
        overall_rating="acceptable",
        mitigations=[
            "Implement trailing stop-loss at 8% below entry",
            "Reduce position size by 20% if sector volatility exceeds 30%",
            "Set hard exit if regulatory news turns materially negative",
            "Monitor institutional flow data for early exit signals",
        ],
    )
