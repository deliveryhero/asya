"""
Multi-Agent Debate - agents argue across rounds until convergence.

Multiple agents independently generate answers to the same question.
In subsequent rounds, each agent sees ALL other agents' answers and
revises its own. The process repeats until agents converge on a
consensus or max rounds are reached. A final judge selects or
synthesizes the best answer.

This pattern significantly improves factual accuracy over single-agent
answers by leveraging diverse reasoning paths.

Pattern: fan-out initial answers -> while not converged -> share all -> fan-out revise -> check

ADK equivalent:
  - Story Teller partial match: parallel writers -> critique selects
  - https://github.com/google/adk-samples/tree/main/python/agents/story-teller
  - No direct ADK sample for multi-round debate (Asya adds this)

Framework references:
  - "Improving Factuality and Reasoning in LLMs through Multiagent Debate"
    (Du et al., 2023) - the seminal paper
  - AutoGen debate pattern via SelectorGroupChat
    https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/selector-group-chat.html
  - Google Cloud "Swarm" pattern (variant)
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Deployment:
  - debater_a, debater_b, debater_c: independent LLM agents (different
    models, temperatures, or system prompts for diversity)
  - convergence_checker: evaluates if agents have reached consensus
  - revise_a, revise_b, revise_c: LLM actors that revise positions
  - final_judge: LLM actor that selects or synthesizes the best answer

Payload contract:
  state["question"]      - the question to debate
  state["positions"]     - list of each agent's current position
  state["round"]         - current debate round
  state["converged"]     - whether agents have converged
  state["final_answer"]  - the consensus or judged answer

NOTE: The revision round uses sequential calls as a workaround. Fan-out
inside while loops is now supported by the compiler -- this example can
be updated to use parallel fan-out for revisions.
"""

import asyncio


async def multi_agent_debate(state: dict) -> dict:
    state["round"] = 0

    # [FAN-OUT: compiled] Round 0 -- each debater generates independently
    state["positions"] = list(await asyncio.gather(
        debater_a(state["question"]),   # [ACTOR: debater_a]
        debater_b(state["question"]),   # [ACTOR: debater_b]
        debater_c(state["question"]),   # [ACTOR: debater_c]
    ))

    # [ROUTER: compiled] Debate rounds until convergence or max rounds
    while True:
        state["round"] += 1

        # [ACTOR: convergence_checker] LLM/logic evaluates consensus
        state = await convergence_checker(state)

        if state.get("converged"):
            break

        if state["round"] >= 3:
            break

        # [ACTORS: revise_*] Each debater revises seeing all positions
        state = await revise_a(state)   # [ACTOR: revise_a]
        state = await revise_b(state)   # [ACTOR: revise_b]
        state = await revise_c(state)   # [ACTOR: revise_c]

    # [ACTOR: final_judge] LLM synthesizes the best answer
    state = await final_judge(state)
    return state


# ---------------------------------------------------------------------------
# Actor stubs -- each becomes a separately deployed AsyncActor.
# Replace `...` with real LLM calls, tool use, or business logic.
# ---------------------------------------------------------------------------


async def debater_a(question: dict) -> dict:
    """[LLM ACTOR] Generate initial position on the question.

    Reads:  question (passed directly, not from state)
    Returns: {position, confidence, reasoning} dict

    Uses a specific prompt style or model configuration to produce
    a distinct perspective. Each debater should use different settings
    (model, temperature, system prompt) to ensure diversity of thought.
    """
    ...  # LLM call: generate independent position on the question


async def debater_b(question: dict) -> dict:
    """[LLM ACTOR] Generate initial position (different perspective).

    Same interface as debater_a. May use a different model, higher
    temperature, or contrarian system prompt.
    """
    ...  # LLM call: generate independent position (different config)


async def debater_c(question: dict) -> dict:
    """[LLM ACTOR] Generate initial position (third perspective).

    Same interface as debater_a. Yet another angle on the question.
    """
    ...  # LLM call: generate independent position (third config)


async def convergence_checker(state: dict) -> dict:
    """[LLM/LOGIC ACTOR] Check if debaters have reached consensus.

    Reads:  state["positions"]
    Writes: state["converged"] (True if consensus reached)

    Compares all positions. Sets converged=True if:
    - All positions agree on key claims
    - Positions are semantically equivalent
    - Disagreements are only on style, not substance

    May use embedding similarity, keyword overlap, or LLM judgment.
    """
    ...  # LLM/logic: compare positions, determine if converged


async def revise_a(state: dict) -> dict:
    """[LLM ACTOR] Debater A revises position seeing all positions.

    Reads:  state["positions"] (all agents' current answers)
    Writes: state["positions"][0] (updated position)

    May strengthen, weaken, or change stance based on other agents'
    arguments. The revision is informed by but not dictated by others.
    """
    ...  # LLM call: revise own position given all other positions


async def revise_b(state: dict) -> dict:
    """[LLM ACTOR] Debater B revises position seeing all positions.

    Same as revise_a but updates state["positions"][1].
    """
    ...  # LLM call: revise own position given all other positions


async def revise_c(state: dict) -> dict:
    """[LLM ACTOR] Debater C revises position seeing all positions.

    Same as revise_a but updates state["positions"][2].
    """
    ...  # LLM call: revise own position given all other positions


async def final_judge(state: dict) -> dict:
    """[LLM ACTOR] Select or synthesize the final answer.

    Reads:  state["positions"]
    Writes: state["final_answer"]

    Produces the final answer by either:
    - Selecting the most well-argued position
    - Synthesizing a consensus from all positions
    - Majority voting on key claims
    """
    ...  # LLM call: judge all final positions, produce consensus answer
