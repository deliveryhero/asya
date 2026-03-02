"""
ReAct Tool Loop - the foundational agentic pattern.

An LLM iterates in a Thought-Action-Observation loop: it reasons about what
to do, selects a tool, executes it, observes the result, and loops until it
produces a final answer.

The flow models the OUTER control loop. Each actor (llm_reason, tool_*)
is an independent AsyncActor. The LLM actor sets tool_calls in the payload;
the router dispatches to the appropriate tool actor.

Pattern: while True -> LLM -> if tool_call -> dispatch tool -> loop

ADK equivalent:
  - BaseLlmFlow.run_async() while-true loop
  - https://github.com/google/adk-python/blob/main/src/google/adk/flows/llm_flows/base_llm_flow.py
  - ADK samples: Customer Service, Personalized Shopping, SWE Benchmark
  - https://github.com/google/adk-samples/tree/main/python/agents/customer-service

Framework references:
  - LangGraph: prebuilt ReAct agent with tools_condition edge
    https://langchain-ai.github.io/langgraph/how-tos/create-react-agent/
  - DSPy: dspy.ReAct("question -> answer", tools=[...])
  - Anthropic: tool_runner.until_done() agentic loop
    https://www.anthropic.com/engineering/building-effective-agents
  - Google Cloud: "Single agent" pattern
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Deployment:
  - llm_reason: LLM actor (e.g., Gemini/Claude with tool schemas)
  - web_search, code_exec, calculator: individual tool actors
  - format_response: post-processing actor

Payload contract:
  state["messages"]    - conversation history
  state["tool_calls"]  - list of {name, args} from LLM (empty = final answer)
  state["tool_name"]   - dispatched tool name (set by router)
  state["observation"]  - tool execution result
"""


async def react_tool_loop(state: dict) -> dict:
    state["messages"] = state.get("messages", [])
    state["iteration"] = 0

    while True:
        state["iteration"] += 1

        # LLM decides: produce tool_calls or final answer
        state = await llm_reason(state)

        # No tool calls = final answer produced
        if not state.get("tool_calls"):
            break

        # Dispatch to the appropriate tool based on LLM's choice
        state["tool_name"] = state["tool_calls"][0]["name"]

        if state["tool_name"] == "web_search":
            state = await web_search(state)
        elif state["tool_name"] == "code_exec":
            state = await code_exec(state)
        elif state["tool_name"] == "calculator":
            state = await calculator(state)
        else:
            state["observation"] = "Unknown tool"

        # Append observation to messages for next LLM turn
        state["messages"] = state.get("messages", [])

        # Safety: max iterations
        if state["iteration"] >= 10:
            break

    state = await format_response(state)
    return state


# --- Handler stubs (each deployed as a separate AsyncActor) ---


async def llm_reason(state: dict) -> dict:
    """LLM actor: receives messages + tool schemas, returns tool_calls or final answer.

    The actor internally calls an LLM API (Gemini, Claude, GPT) with the
    conversation history and available tool definitions. If the LLM wants
    to use a tool, it populates state["tool_calls"]. Otherwise, it writes
    the final answer to state["response"].
    """
    iteration = state.get("iteration", 0)
    messages = state.get("messages", [])

    if iteration == 1:
        state["tool_calls"] = [{"id": "call_1", "name": "web_search", "args": {"query": "latest developments in quantum computing 2026"}}]
        messages.append({"role": "assistant", "content": "Let me search for recent information about quantum computing."})
    elif iteration == 2:
        state["tool_calls"] = [{"id": "call_2", "name": "calculator", "args": {"expression": "2048 * 365"}}]
        messages.append({"role": "assistant", "content": "Now let me calculate the total processing capacity."})
    else:
        state["tool_calls"] = []
        state["response"] = "Based on my research, quantum computing has made significant progress in 2026 with new qubit stability records. The total processing capacity of current systems is approximately 747,520 operations per year."
        messages.append({"role": "assistant", "content": state["response"]})

    state["messages"] = messages
    return state


async def web_search(state: dict) -> dict:
    """Tool actor: execute a web search query, return results as observation."""
    tool_call = state["tool_calls"][0]
    query = tool_call["args"]["query"]
    state["observation"] = f"Search results for '{query}': Researchers at MIT and Google achieved 99.9% qubit coherence time in February 2026. IBM announced a 1000-qubit processor with breakthrough error correction. Nature published a study showing quantum advantage in drug discovery simulations."
    state.setdefault("messages", []).append(
        {"role": "tool", "tool_call_id": tool_call["id"], "content": state["observation"]}
    )
    return state


async def code_exec(state: dict) -> dict:
    """Tool actor: execute code in a sandboxed environment, return output."""
    tool_call = state["tool_calls"][0]
    code = tool_call["args"].get("code", "")
    state["observation"] = f"Code execution output:\n{code}\n---\nSuccessfully executed. Output: 42"
    state.setdefault("messages", []).append(
        {"role": "tool", "tool_call_id": tool_call["id"], "content": state["observation"]}
    )
    return state


async def calculator(state: dict) -> dict:
    """Tool actor: evaluate a mathematical expression."""
    tool_call = state["tool_calls"][0]
    expression = tool_call["args"]["expression"]
    state["observation"] = f"Calculated {expression} = 747520"
    state.setdefault("messages", []).append(
        {"role": "tool", "tool_call_id": tool_call["id"], "content": state["observation"]}
    )
    return state


async def format_response(state: dict) -> dict:
    """Post-processing: format the final response for the user."""
    response = state.get("response", "")
    messages = state.get("messages", [])

    state["formatted_response"] = {
        "answer": response,
        "iterations": state.get("iteration", 0),
        "conversation_length": len(messages)
    }
    return state
