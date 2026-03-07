"""
Tests for the routing_classifier agentic flow.

Covers:
- classifier stub: keyword-based category detection
- billing/technical/account/general stubs: each writes state["resolution"]
- format_reply stub: formats resolution into a labelled reply
- full flow function: all stubs chained
- compiled routers: routing decisions via ABI SET commands
"""

import pytest
from routing_classifier import (
    account_agent,
    billing_agent,
    classifier,
    format_reply,
    general_agent,
    routing_classifier,
    technical_agent,
)


# ── classifier stub ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message, expected_category",
    [
        ("I need help with my invoice", "billing"),
        ("There's a charge I don't recognise", "billing"),
        ("the app is crashing on startup", "technical"),
        ("my password doesn't work", "account"),
        ("I want to update my subscription plan", "account"),
        ("just saying hi", "general"),
    ],
)
async def test_classifier_categories(run_handler, message, expected_category):
    result = await run_handler(classifier({"message": message}))
    assert result.payload["category"] == expected_category


# ── domain agent stubs ────────────────────────────────────────────────────────


async def test_billing_agent_writes_resolution(run_handler):
    state = {"message": "What happened to my payment?", "category": "billing"}
    result = await run_handler(billing_agent(state))

    assert "resolution" in result.payload
    assert len(result.payload["resolution"]) > 0
    # original fields preserved
    assert result.payload["category"] == "billing"


async def test_technical_agent_writes_resolution(run_handler):
    state = {"message": "API is timing out", "category": "technical"}
    result = await run_handler(technical_agent(state))

    assert "resolution" in result.payload


async def test_account_agent_writes_resolution(run_handler):
    state = {"message": "reset my password", "category": "account"}
    result = await run_handler(account_agent(state))

    assert "resolution" in result.payload


async def test_general_agent_writes_resolution(run_handler):
    state = {"message": "tell me about your product", "category": "general"}
    result = await run_handler(general_agent(state))

    assert "resolution" in result.payload


# ── format_reply stub ─────────────────────────────────────────────────────────


async def test_format_reply_includes_category_label(run_handler):
    state = {
        "category": "billing",
        "resolution": "Your refund has been processed.",
    }
    result = await run_handler(format_reply(state))

    reply = result.payload["formatted_reply"]
    assert "Billing Support" in reply
    assert "Your refund has been processed." in reply
    assert "help.example.com" in reply


@pytest.mark.parametrize(
    "category, expected_label",
    [
        ("billing", "Billing Support"),
        ("technical", "Technical Support"),
        ("account", "Account Management"),
        ("general", "Customer Service"),
    ],
)
async def test_format_reply_labels(run_handler, category, expected_label):
    state = {"category": category, "resolution": "Some resolution."}
    result = await run_handler(format_reply(state))
    assert expected_label in result.payload["formatted_reply"]


# ── full flow function ────────────────────────────────────────────────────────


async def test_routing_classifier_billing_path(run_handler):
    state = {"message": "I have a question about my billing charge"}
    result = await run_handler(routing_classifier(state))

    payload = result.payload
    assert payload["category"] == "billing"
    assert "resolution" in payload
    assert "formatted_reply" in payload
    assert "Billing Support" in payload["formatted_reply"]


async def test_routing_classifier_technical_path(run_handler):
    state = {"message": "app is not working and keeps crashing"}
    result = await run_handler(routing_classifier(state))

    assert result.payload["category"] == "technical"
    assert "Technical Support" in result.payload["formatted_reply"]


async def test_routing_classifier_general_fallback(run_handler):
    state = {"message": "just browsing around"}
    result = await run_handler(routing_classifier(state))

    assert result.payload["category"] == "general"
    assert "Customer Service" in result.payload["formatted_reply"]


# ── compiled routers (sync generators) ───────────────────────────────────────


async def test_start_router_chains_to_classifier_and_conditional(run_handler, monkeypatch, load_routers):
    """start_routing_classifier sets classifier then the first conditional router."""
    routers = load_routers("routing_classifier")
    monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")

    result = await run_handler(routers.start_routing_classifier({"message": "hello"}))

    set_cmds = [e for e in result.abi if e[0] == "SET" and e[1] == ".route.next[:0]"]
    assert len(set_cmds) == 1
    actors = set_cmds[0][2]
    assert actors[0] == "actor-classifier"
    assert "actor-router_routing_classifier_line_43_if" in actors


@pytest.mark.parametrize(
    "category, expected_agent",
    [
        ("billing", "actor-billing_agent"),
        ("technical", "actor-router_routing_classifier_line_45_if"),  # passes to next router
    ],
)
async def test_billing_conditional_router(run_handler, monkeypatch, load_routers, category, expected_agent):
    """The line_43_if router routes billing to billing_agent, others to next router."""
    routers = load_routers("routing_classifier")
    monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")

    payload = {"category": category, "message": "test"}
    result = await run_handler(routers.router_routing_classifier_line_43_if(payload))

    set_cmds = [e for e in result.abi if e[0] == "SET" and e[1] == ".route.next[:0]"]
    assert len(set_cmds) == 1
    actors = set_cmds[0][2]
    assert expected_agent in actors
    assert result.payload == payload


async def test_account_general_conditional_router(run_handler, monkeypatch, load_routers):
    """The line_47_if router sends account to account_agent, else to general_agent."""
    routers = load_routers("routing_classifier")
    monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")

    # account path
    result = await run_handler(routers.router_routing_classifier_line_47_if({"category": "account"}))
    actors = next(e[2] for e in result.abi if e[0] == "SET")
    assert "actor-account_agent" in actors

    # general (else) path
    result = await run_handler(routers.router_routing_classifier_line_47_if({"category": "something-else"}))
    actors = next(e[2] for e in result.abi if e[0] == "SET")
    assert "actor-general_agent" in actors
