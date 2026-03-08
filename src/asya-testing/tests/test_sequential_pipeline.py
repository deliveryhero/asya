"""
Tests for the sequential_pipeline agentic flow.

Covers:
- Each handler stub individually (function adapters, coroutine path)
- The full 4-hop chain simulated locally (multi-hop flow)
- The compiled start router (sync generator, ABI SET path)
"""

from sequential_pipeline import (
    data_analyst,
    execution_planner,
    risk_evaluator,
    sequential_pipeline,
    trading_analyst,
)


# ── Individual handler stubs ──────────────────────────────────────────────────


async def test_data_analyst_populates_market_data(run_handler):
    result = await run_handler(data_analyst({"topic": "AI semiconductors"}))

    payload = result.payload
    assert payload["topic"] == "AI semiconductors"
    assert "market_data" in payload
    md = payload["market_data"]
    assert md["topic"] == "AI semiconductors"
    assert len(md["trends"]) == 3
    assert "prices" in md
    assert "news" in md
    # upstream fields preserved
    assert payload["topic"] == "AI semiconductors"


async def test_trading_analyst_requires_market_data(run_handler):
    # Provide the market_data that data_analyst would have set
    state = {
        "topic": "AI semiconductors",
        "market_data": {
            "prices": {"current": 200.0},
        },
    }
    result = await run_handler(trading_analyst(state))

    payload = result.payload
    assert "strategies" in payload
    assert len(payload["strategies"]) == 5
    # entry/exit prices are derived from current price
    for strategy in payload["strategies"]:
        assert "name" in strategy
        assert "entry" in strategy
        assert "exit" in strategy
        assert strategy["entry"] > 0


async def test_execution_planner_selects_strategies(run_handler):
    state = {
        "strategies": [
            {"name": "StratA", "entry": 100.0, "exit": 115.0, "rationale": "r1"},
            {"name": "StratB", "entry": 97.0, "exit": 108.0, "rationale": "r2"},
            {"name": "StratC", "entry": 99.0, "exit": 112.0, "rationale": "r3"},
        ]
    }
    result = await run_handler(execution_planner(state))

    plan = result.payload["exec_plan"]
    assert plan["selected_strategies"] == ["StratA", "StratC"]
    assert len(plan["actions"]) == 3
    assert plan["total_capital_allocated"] > 0


async def test_risk_evaluator_produces_assessment(run_handler):
    state = {
        "market_data": {"prices": {"current": 150.0}},
        "strategies": [{"name": "S"}],
        "exec_plan": {"max_position_size": 800},
    }
    result = await run_handler(risk_evaluator(state))

    assessment = result.payload["risk_assessment"]
    assert assessment["overall_risk_rating"] == "acceptable"
    assert "market_risk" in assessment
    assert "mitigations" in assessment
    assert len(assessment["mitigations"]) > 0


# ── Full pipeline chain ───────────────────────────────────────────────────────


async def test_full_pipeline_chain(run_handler):
    """Simulate 4 actor hops without any infrastructure."""
    state: dict = {"topic": "quantum computing"}

    # Hop 1: data analyst
    result = await run_handler(data_analyst(state))
    state = result.payload
    assert "market_data" in state

    # Hop 2: trading analyst
    result = await run_handler(trading_analyst(state))
    state = result.payload
    assert "strategies" in state

    # Hop 3: execution planner
    result = await run_handler(execution_planner(state))
    state = result.payload
    assert "exec_plan" in state

    # Hop 4: risk evaluator
    result = await run_handler(risk_evaluator(state))
    state = result.payload
    assert "risk_assessment" in state
    assert state["risk_assessment"]["overall_risk_rating"] == "acceptable"

    # All earlier fields still present
    assert state["topic"] == "quantum computing"
    assert "market_data" in state
    assert "strategies" in state


async def test_full_pipeline_function(run_handler):
    """The flow-level function runs the same chain in one call."""
    result = await run_handler(sequential_pipeline({"topic": "biotech"}))

    payload = result.payload
    # All four stages must have contributed
    assert "market_data" in payload
    assert "strategies" in payload
    assert "exec_plan" in payload
    assert "risk_assessment" in payload


# ── Compiled start router (sync generator) ───────────────────────────────────


async def test_start_router_sets_actor_chain(run_handler, monkeypatch, load_routers):
    """start_sequential_pipeline sets route.next to all 4 actors in order."""
    routers = load_routers("sequential_pipeline")

    # resolve() normally reads ASYA_HANDLER_* env vars; patch it to return
    # a predictable actor name from the handler suffix.
    monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")

    payload = {"topic": "semiconductors"}
    result = await run_handler(routers.start_sequential_pipeline(payload))

    # The start router should have emitted exactly one SET for route.next
    set_cmds = [e for e in result.abi if e[0] == "SET" and e[1] == ".route.next[:0]"]
    assert len(set_cmds) == 1

    actors = set_cmds[0][2]
    assert actors == [
        "actor-data_analyst",
        "actor-trading_analyst",
        "actor-execution_planner",
        "actor-risk_evaluator",
    ]

    # Payload passes through unchanged
    assert result.payload == payload
