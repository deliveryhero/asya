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
  - debater_a, debater_b, debater_c: independent LLM agents
  - convergence_checker: evaluates if agents have reached consensus
  - final_judge: selects or synthesizes the best answer

Payload contract:
  state["question"]      - the question to debate
  state["positions"]     - list of each agent's current position
  state["round"]         - current debate round
  state["converged"]     - whether agents have converged
  state["final_answer"]  - the consensus or judged answer

NOTE: The revision round uses sequential calls as a workaround. Ideally
each round would use fan-out for parallel revision, but fan-out inside
while loops requires additional compiler testing.
"""

import asyncio


async def multi_agent_debate(state: dict) -> dict:
    state["round"] = 0

    # Round 0: each debater generates an independent initial position
    # (fan-out: all three run in parallel)
    state["positions"] = list(await asyncio.gather(
        debater_a(state["question"]),
        debater_b(state["question"]),
        debater_c(state["question"]),
    ))

    # Debate rounds: agents revise their positions seeing all others
    while True:
        state["round"] += 1

        # Check convergence: have agents reached consensus?
        state = await convergence_checker(state)

        if state.get("converged"):
            break

        if state["round"] >= 3:
            break

        # Each debater revises seeing all positions
        # NOTE: Ideally this would be fan-out, but fan-out inside
        # while loops is a compiler edge case. Using sequential
        # revision as workaround.
        state = await revise_a(state)
        state = await revise_b(state)
        state = await revise_c(state)

    # Final judge synthesizes the best answer
    state = await final_judge(state)
    return state


# --- Handler stubs ---


async def debater_a(question: dict) -> dict:
    """LLM actor: generate initial position on the question.

    Uses a specific prompt style or model configuration to produce
    a distinct perspective. Returns its position as a dict.
    """
    return {
        "position": "AI will significantly accelerate scientific discovery within the next 5 years",
        "confidence": 0.85,
        "reasoning": [
            "Recent breakthroughs in protein folding (AlphaFold) demonstrate massive acceleration",
            "AI can process vastly more research papers than human researchers",
            "Automated hypothesis generation and testing are becoming viable"
        ]
    }


async def debater_b(question: dict) -> dict:
    """LLM actor: generate initial position (different perspective).

    May use a different model, temperature, or system prompt than
    debater_a to ensure diversity of thought.
    """
    return {
        "position": "AI impact on science will be incremental, not transformative in the near term",
        "confidence": 0.75,
        "reasoning": [
            "Most scientific breakthroughs require deep domain expertise and intuition",
            "AI tools are assistive but don't replace the creative process of discovery",
            "Integration challenges and validation requirements slow adoption",
            "Historical precedent shows technology adoption in science is gradual"
        ]
    }


async def debater_c(question: dict) -> dict:
    """LLM actor: generate initial position (third perspective).

    Provides yet another angle on the question.
    """
    return {
        "position": "AI will accelerate some fields dramatically while having minimal impact on others",
        "confidence": 0.70,
        "reasoning": [
            "Data-rich fields (genomics, materials science) will see major acceleration",
            "Fields requiring physical experimentation will see limited direct benefit",
            "Impact depends heavily on data availability and problem structure",
            "Uneven distribution of AI research funding will create disparities"
        ]
    }


async def convergence_checker(state: dict) -> dict:
    """LLM/Logic actor: check if debaters have reached consensus.

    Compares state["positions"]. Sets state["converged"] = True if:
    - All positions agree on key claims
    - Positions are semantically equivalent
    - Disagreements are only on style, not substance

    May use embedding similarity, keyword overlap, or LLM judgment.
    """
    round_num = state.get("round", 0)

    if round_num < 3:
        state["converged"] = False
    else:
        state["converged"] = True

    return state


async def revise_a(state: dict) -> dict:
    """LLM actor: debater A revises position seeing all positions.

    Reads state["positions"] (all agents' current answers) and
    updates its own position. May strengthen, weaken, or change
    its stance based on other agents' arguments.
    """
    positions = state.get("positions", [])
    round_num = state.get("round", 0)

    if round_num == 1:
        positions[0] = {
            "position": "AI will significantly accelerate scientific discovery in data-rich fields within 5 years",
            "confidence": 0.82,
            "reasoning": [
                "Acknowledging that impact will vary by field (point from debater C)",
                "AlphaFold and similar breakthroughs show concrete acceleration",
                "But recognizing integration challenges (point from debater B)",
                "Focusing prediction on data-rich domains where evidence is strongest"
            ]
        }
    elif round_num == 2:
        positions[0] = {
            "position": "AI will moderately accelerate scientific discovery across multiple fields, with transformative impact in data-rich domains",
            "confidence": 0.78,
            "reasoning": [
                "Converging toward balanced view acknowledging both opportunities and constraints",
                "Transformative in genomics, materials science, drug discovery",
                "Incremental improvement in fields requiring physical experimentation",
                "Timeline and magnitude of impact vary significantly by domain"
            ]
        }

    state["positions"] = positions
    return state


async def revise_b(state: dict) -> dict:
    """LLM actor: debater B revises position seeing all positions."""
    positions = state.get("positions", [])
    round_num = state.get("round", 0)

    if round_num == 1:
        positions[1] = {
            "position": "AI will provide incremental but meaningful improvements to scientific research",
            "confidence": 0.77,
            "reasoning": [
                "Debater A's AlphaFold example is compelling for specific domains",
                "Maintaining that creative discovery requires human insight",
                "But acknowledging AI can accelerate specific research tasks",
                "Timeline may be faster in computational fields than initially thought"
            ]
        }
    elif round_num == 2:
        positions[1] = {
            "position": "AI will moderately accelerate scientific discovery, with major impact in computational domains",
            "confidence": 0.79,
            "reasoning": [
                "Converging toward nuanced view of domain-specific impact",
                "Major acceleration in data analysis and pattern recognition tasks",
                "Modest improvement in hypothesis generation and experimental design",
                "Human expertise remains critical but AI amplifies productivity"
            ]
        }

    state["positions"] = positions
    return state


async def revise_c(state: dict) -> dict:
    """LLM actor: debater C revises position seeing all positions."""
    positions = state.get("positions", [])
    round_num = state.get("round", 0)

    if round_num == 1:
        positions[2] = {
            "position": "AI impact will be highly domain-dependent, transformative in some fields and incremental in others",
            "confidence": 0.80,
            "reasoning": [
                "Debater A's optimism is justified for computational biology",
                "Debater B's caution is appropriate for experimental sciences",
                "Data availability and problem structure are key determinants",
                "5-year timeline is reasonable for data-rich fields specifically"
            ]
        }
    elif round_num == 2:
        positions[2] = {
            "position": "AI will moderately accelerate scientific discovery overall, with transformative impact in data-rich computational domains",
            "confidence": 0.81,
            "reasoning": [
                "Consensus emerging around domain-specific variation in impact",
                "Transformative: genomics, drug discovery, materials science",
                "Moderate: climate modeling, physics simulations",
                "Incremental: fields requiring physical lab experimentation",
                "Overall acceleration is real but magnitude varies significantly"
            ]
        }

    state["positions"] = positions
    return state


async def final_judge(state: dict) -> dict:
    """LLM actor: select or synthesize the final answer.

    Reads all final positions in state["positions"]. Produces
    state["final_answer"] by either:
    - Selecting the most well-argued position
    - Synthesizing a consensus from all positions
    - Majority voting on key claims
    """
    positions = state.get("positions", [])

    state["final_answer"] = {
        "consensus": "AI will moderately accelerate scientific discovery across fields, with transformative impact in data-rich computational domains within 5 years",
        "confidence": 0.80,
        "key_agreements": [
            "Impact varies significantly by scientific domain",
            "Data-rich fields (genomics, materials science) will see major acceleration",
            "Fields requiring physical experimentation will see incremental improvement",
            "Human expertise remains essential but AI amplifies productivity"
        ],
        "uncertainty_factors": [
            "Rate of AI capability improvement is hard to predict",
            "Adoption timelines depend on institutional and regulatory factors",
            "Uneven research funding may create disparities"
        ],
        "synthesis_method": "convergent_consensus",
        "debate_rounds": state.get("round", 0),
        "positions_reviewed": len(positions)
    }
    return state
