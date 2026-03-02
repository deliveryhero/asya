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


async def voting_ensemble(state: dict) -> dict:
    # Fan-out: three agents tackle the same task independently
    # Each uses different LLM settings (temperature, style, model)
    state["candidates"] = [
        creative_writer(state["prompt"]),
        analytical_writer(state["prompt"]),
        concise_writer(state["prompt"]),
    ]

    # Judge evaluates all candidates and selects the best
    state = await judge(state)
    return state


# --- Handler stubs ---


async def creative_writer(prompt: dict) -> dict:
    """LLM actor (high temperature): generate a creative, expressive response.

    Uses high temperature (0.9+) for diverse, imaginative output.
    May use a model optimized for creative writing.
    """
    return prompt


async def analytical_writer(prompt: dict) -> dict:
    """LLM actor (low temperature): generate a precise, analytical response.

    Uses low temperature (0.2) for focused, factual output.
    May use a model optimized for reasoning (e.g., o3, Gemini Pro).
    """
    return prompt


async def concise_writer(prompt: dict) -> dict:
    """LLM actor (medium temperature): generate a concise, clear response.

    Uses medium temperature (0.5) with instructions emphasizing brevity.
    May use a fast model (Haiku, Flash) for efficiency.
    """
    return prompt


async def judge(state: dict) -> dict:
    """LLM actor: evaluate candidates and select the best.

    Reads state["candidates"], evaluates each against criteria
    (accuracy, clarity, completeness, style). Sets:
    - state["selected"]: the winning output
    - state["judge_rationale"]: explanation of the selection

    May also synthesize a hybrid combining the best parts of
    multiple candidates.
    """
    return state
