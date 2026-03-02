"""
Evaluator-Optimizer - generator-critic refinement loop.

One actor generates output; another evaluates it against criteria. If the
evaluation fails, feedback is sent back to the generator for revision.
The loop continues until quality thresholds are met or max iterations reached.

Differs from single-agent Reflection: here the generator and evaluator are
SEPARATE actors (possibly different models, different prompts, different
scaling characteristics).

Pattern: while True -> generator -> evaluator -> if good enough break; else feedback -> loop

ADK equivalent:
  - Image Scoring: Prompt Gen -> Image Gen -> Scoring Agent -> Checker (loop)
  - https://github.com/google/adk-samples/tree/main/python/agents/image-scoring
  - LLM Auditor: Critic extracts claims + verifies -> Reviser corrects
  - https://github.com/google/adk-samples/tree/main/python/agents/llm-auditor
  - Blog Writer: iterative user feedback at each stage
  - https://github.com/google/adk-samples/tree/main/python/agents/blog-writer

Framework references:
  - Anthropic "Evaluator-Optimizer" workflow pattern
    https://www.anthropic.com/engineering/building-effective-agents
  - Google Cloud "Multi-agent (loop) - Review and critique" pattern
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system
  - ADK LoopAgent with exit_condition callback
  - LangGraph: custom graph with generate/evaluate nodes + conditional edge

Deployment:
  - generator: LLM actor that produces content
  - evaluator: LLM actor that scores and critiques (may use different model)
  - polisher: optional final formatting after loop exits

Payload contract:
  state["task"]          - what to generate
  state["draft"]         - current draft (set/updated by generator)
  state["score"]         - quality score 0-100 (set by evaluator)
  state["feedback"]      - specific critique (set by evaluator)
  state["iteration"]     - loop counter
  state["final_output"]  - polished output (set by polisher)
"""

import os

# static deployment-time configuration can be passed via env vars:
SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", 85))
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", 5))


async def evaluator_optimizer(state: dict) -> dict:
    state["iteration"] = 0

    while True:
        state["iteration"] += 1

        # Generate: produce or revise a draft
        state = await generator(state)

        # Evaluate: score the draft and produce feedback
        state = await evaluator(state)

        # Exit: quality threshold met
        if state.get("score", 0) >= SCORE_THRESHOLD:
            break

        # Exit: max iterations
        if state["iteration"] >= MAX_ITERATIONS:
            break

        # Feedback flows back to generator on next iteration
        # (state["feedback"] is already set by evaluator)

    # Final polish
    state = await polisher(state)
    return state


# --- Handler stubs ---


async def generator(state: dict) -> dict:
    """LLM actor: generate or revise content.

    First iteration: generates from state["task"].
    Subsequent iterations: revises state["draft"] using state["feedback"].

    The generator sees the evaluator's feedback and improves accordingly.
    May use a creative model (high temperature) for initial drafts and
    become more focused (lower temperature) in later iterations.
    """
    task = state["task"]
    feedback = state.get("feedback")

    if not feedback:
        state["draft"] = f"Initial draft for task: {task}. This is a preliminary version with basic coverage but lacking detail and polish."
    else:
        state["draft"] = f"Revised draft for task: {task}. Improvements based on feedback: {feedback}. Now includes more detail, better structure, and clearer arguments."

    return state


async def evaluator(state: dict) -> dict:
    """LLM actor: score and critique the draft.

    Reads state["draft"], evaluates against criteria. Sets:
    - state["score"]: 0-100 quality assessment
    - state["feedback"]: specific, actionable critique

    May use a different model than the generator (e.g., a reasoning
    model for evaluation, a creative model for generation). The
    evaluator should be calibrated so that scores are meaningful
    and consistent across iterations.
    """
    draft = state["draft"]
    iteration = state.get("iteration", 0)

    if iteration == 1:
        state["score"] = 55
        state["feedback"] = "Draft lacks sufficient detail and supporting evidence. Structure needs improvement. Arguments are not well-developed."
    elif iteration == 2:
        state["score"] = 72
        state["feedback"] = "Much better structure and detail. Could still use stronger transitions and more concrete examples in the conclusion."
    else:
        state["score"] = 90
        state["feedback"] = "Excellent quality. Well-structured, detailed, and persuasive. Minor polish could improve flow."

    return state


async def polisher(state: dict) -> dict:
    """Actor: final formatting and cleanup.

    Takes state["draft"] (the last accepted version) and applies
    formatting, citation, and style adjustments. Sets state["final_output"].
    """
    draft = state["draft"]
    state["final_output"] = f"[POLISHED] {draft} [Formatted with proper citations, consistent style, and professional presentation]"
    return state
