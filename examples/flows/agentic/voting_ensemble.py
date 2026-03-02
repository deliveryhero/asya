"""
Voting Ensemble - same task executed by multiple agents, best selected.

Multiple agents independently generate solutions to the SAME task.
A judge agent evaluates all outputs and selects the best one (or
synthesizes a consensus). This trades compute cost for output quality.

Pattern: fan-out [agent_A, agent_B, agent_C] (same task) -> judge selects best

ADK equivalent:
  - Story Teller: Creative Writer (high temp) + Focused Writer (low temp)
    generate competing drafts, Critique Agent selects best
  - https://github.com/google/adk-samples/tree/main/python/agents/story-teller

Framework references:
  - Anthropic "Parallelization (Voting)" pattern
    https://www.anthropic.com/engineering/building-effective-agents
  - LLM-as-Judge pattern (Zheng et al., 2023)
  - Multi-Agent Debate simplified to single round + judge
    (Du et al., "Improving Factuality and Reasoning", 2023)

Deployment:
  - creative_writer, analytical_writer, concise_writer: different LLM
    configurations (temperature, prompt style) for the same task
  - judge: evaluator LLM that selects or synthesizes the best output

Payload contract:
  state["prompt"]        - the writing prompt / task description
  state["candidates"]    - list of candidate outputs (set by fan-out)
  state["selected"]      - the chosen output (set by judge)
  state["judge_rationale"] - explanation of why this was chosen
"""

import asyncio


async def voting_ensemble(state: dict) -> dict:
    # Fan-out: three agents tackle the same task independently
    # Each uses different LLM settings (temperature, style, model)
    state["candidates"] = list(await asyncio.gather(
        creative_writer(state["prompt"]),
        analytical_writer(state["prompt"]),
        concise_writer(state["prompt"]),
    ))

    # Judge evaluates all candidates and selects the best
    state = await judge(state)
    return state


# --- Handler stubs ---


async def creative_writer(prompt: dict) -> dict:
    """LLM actor (high temperature): generate a creative, expressive response.

    Uses high temperature (0.9+) for diverse, imaginative output.
    May use a model optimized for creative writing.
    """
    return {
        "text": "Picture a world where machines don't just compute but truly understand - where algorithms dance with data in elegant symphonies of meaning. This is the promise of modern AI: not cold calculation, but intelligent partnership. Like a master craftsman shaping raw materials into art, neural networks transform information into insight, creating bridges between human intention and digital capability.",
        "style": "creative",
        "word_count": 62,
    }


async def analytical_writer(prompt: dict) -> dict:
    """LLM actor (low temperature): generate a precise, analytical response.

    Uses low temperature (0.2) for focused, factual output.
    May use a model optimized for reasoning (e.g., o3, Gemini Pro).
    """
    return {
        "text": "Artificial intelligence systems process input data through mathematical transformations to produce outputs. Modern approaches leverage deep learning architectures trained on large datasets. Key components include feature extraction, pattern recognition, and optimization algorithms. Performance metrics such as accuracy, precision, and recall quantify model effectiveness. Implementation requires careful consideration of computational resources, data quality, and algorithmic complexity.",
        "style": "analytical",
        "word_count": 57,
    }


async def concise_writer(prompt: dict) -> dict:
    """LLM actor (medium temperature): generate a concise, clear response.

    Uses medium temperature (0.5) with instructions emphasizing brevity.
    May use a fast model (Haiku, Flash) for efficiency.
    """
    return {
        "text": "AI systems use neural networks to learn patterns from data and make predictions. They excel at tasks like image recognition, language processing, and decision support. Success depends on quality training data and appropriate model architecture.",
        "style": "concise",
        "word_count": 38,
    }


async def judge(state: dict) -> dict:
    """LLM actor: evaluate candidates and select the best.

    Reads state["candidates"], evaluates each against criteria
    (accuracy, clarity, completeness, style). Sets:
    - state["selected"]: the winning output
    - state["judge_rationale"]: explanation of the selection

    May also synthesize a hybrid combining the best parts of
    multiple candidates.
    """
    candidates = state["candidates"]

    state["selected"] = candidates[1]
    state["judge_rationale"] = (
        "Selected the analytical response for its comprehensive coverage of key concepts "
        "and precise technical accuracy. While the creative version offers engaging prose "
        "and the concise version provides clarity, the analytical approach best balances "
        "depth with factual rigor. It systematically addresses core components, performance "
        "metrics, and implementation considerations without sacrificing accessibility."
    )

    return state
