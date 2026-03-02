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
  - synthesizer: LLM actor that produces final output from step results

Payload contract:
  state["goal"]          - the user's original objective
  state["plan"]          - list of step descriptions (set by planner)
  state["current_step"]  - index of current step being executed
  state["step_results"]  - accumulated results from completed steps
  state["completed"]     - whether the plan is fully executed

Note on control flow: The while loop and step counter are pure state
transformations -- they compile into router actors. Only the function
calls (planner, executor, etc.) become real deployed actors.
"""


async def plan_and_execute(state: dict) -> dict:
    state["current_step"] = 0
    state["step_results"] = []

    state = await planner(state)

    while state["current_step"] < len(state.get("plan", [])):
        state = await executor(state)

        state["current_step"] += 1

        if state["current_step"] < len(state.get("plan", [])):
            state = await re_planner(state)

    state["completed"] = True
    state = await synthesizer(state)
    return state


# ---------------------------------------------------------------------------
# Actor stubs -- each becomes a separately deployed AsyncActor.
# Replace `...` with real LLM calls, tool use, or business logic.
# ---------------------------------------------------------------------------


async def planner(state: dict) -> dict:
    """LLM actor: decompose goal into an ordered list of steps.

    Reads:  state["goal"]
    Writes: state["plan"] (list of step description strings)
            state["step_results"] (initialized to [])

    Each step should be atomic and independently executable. The planner
    reasons about dependencies and orders steps appropriately.
    """
    ...  # LLM call: goal -> ordered list of atomic steps


async def executor(state: dict) -> dict:
    """LLM+tools actor: execute a single step from the plan.

    Reads:  state["plan"][state["current_step"]]
    Writes: appends to state["step_results"]

    Has access to tools (web search, code execution, file operations).
    Executes exactly one step and records the result.
    """
    ...  # LLM call with tools: execute plan[current_step], record result


async def re_planner(state: dict) -> dict:
    """LLM actor: review progress and adjust the remaining plan.

    Reads:  state["plan"], state["step_results"], state["current_step"]
    Writes: state["plan"] (may add, remove, or reorder remaining steps)

    This is what makes plan-and-execute adaptive -- the re-planner can
    modify the remaining plan based on what was learned during execution.
    Without this actor, the pattern is just a static sequential pipeline.
    """
    ...  # LLM call: given results so far, adjust remaining plan steps


async def synthesizer(state: dict) -> dict:
    """LLM actor: produce final output from all step results.

    Reads:  state["step_results"], state["goal"]
    Writes: state["final_output"]

    Combines all completed step results into a coherent final response.
    """
    ...  # LLM call: step_results -> coherent final output
