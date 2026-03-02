"""
Plan-and-Execute - separate planning from execution.

A planner LLM decomposes a complex goal into a multi-step plan. An executor
processes each step using tools. After each step, a re-planner reviews
progress and adjusts the remaining plan.

Differs from ReAct: ReAct decides one step at a time. Plan-and-Execute
commits to a full plan upfront, reducing total LLM calls for long tasks.

Pattern: planner -> while steps remain -> executor -> re-planner -> loop

ADK equivalent:
  - Deep Search sample (plan approval phase -> autonomous execution phase)
  - https://github.com/google/adk-samples/tree/main/python/agents/deep-search
  - Retail AI Location Strategy (7 sequential agents with plan)
  - https://github.com/google/adk-samples/tree/main/python/agents/retail-ai-location-strategy

Framework references:
  - LangGraph Plan-and-Execute tutorial
    https://langchain-ai.github.io/langgraph/tutorials/plan-and-execute/plan-and-execute/
  - BabyAGI (original plan-and-execute agent)
  - "Plan-and-Solve" (Wang et al., 2023)

Deployment:
  - planner: LLM actor that generates ordered task list
  - executor: LLM actor with tools for executing individual steps
  - re_planner: LLM actor that reviews progress and adjusts remaining steps
  - synthesizer: actor that produces final output from step results

Payload contract:
  state["goal"]          - the user's original objective
  state["plan"]          - list of step descriptions (set by planner)
  state["current_step"]  - index of current step being executed
  state["step_results"]  - accumulated results from completed steps
  state["completed"]     - whether the plan is fully executed
"""


async def plan_and_execute(state: dict) -> dict:
    state["current_step"] = 0

    # Phase 1: Generate the plan
    state = await planner(state)

    # Phase 2: Execute each step with optional re-planning
    while state["current_step"] < len(state.get("plan", [])):
        # Execute the current step
        state = await executor(state)

        # Accumulate result
        state["current_step"] += 1

        # Re-plan: adjust remaining steps based on what we learned
        if state["current_step"] < len(state.get("plan", [])):
            state = await re_planner(state)

    # Phase 3: Synthesize final output from all step results
    state["completed"] = True
    state = await synthesizer(state)
    return state


# --- Handler stubs ---


async def planner(state: dict) -> dict:
    """LLM actor: decompose state["goal"] into an ordered list of steps.

    Receives the user's goal and produces state["plan"] - a list of
    step descriptions. Each step should be atomic and independently
    executable. The planner reasons about dependencies between steps
    and orders them appropriately.

    Example output:
      state["plan"] = [
          "Search for recent papers on topic X",
          "Extract key findings from top 3 papers",
          "Compare findings with existing knowledge",
          "Write synthesis report"
      ]
    """
    return state


async def executor(state: dict) -> dict:
    """LLM actor with tools: execute a single step from the plan.

    Reads state["plan"][state["current_step"]] to know what to do.
    Has access to tools (web search, code execution, file operations).
    Writes its result to state["step_results"].
    """
    return state


async def re_planner(state: dict) -> dict:
    """LLM actor: review progress and adjust the remaining plan.

    Receives the original plan, completed step results, and remaining
    steps. May add, remove, or reorder remaining steps based on what
    was learned during execution. This is what makes plan-and-execute
    adaptive (unlike a pure sequential pipeline).
    """
    return state


async def synthesizer(state: dict) -> dict:
    """Actor: produce final output from all accumulated step results.

    Combines state["step_results"] into a coherent final response.
    May use an LLM for synthesis or simple programmatic aggregation.
    """
    return state
