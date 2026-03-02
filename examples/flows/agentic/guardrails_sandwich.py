"""
Guardrails Sandwich - safety pre/post validation wrapping a core agent.

Wraps any agent pipeline with input validation (pre-processing) and output
validation (post-processing). If either validation fails, the flow routes
to a fallback path instead of passing unsafe content through.

The try/except catches safety violations thrown by the validators.

Pattern: try: input_validator -> core_agent -> output_validator except: -> fallback

ADK equivalent:
  - Safety Plugins: 4-point interception (pre-model, post-model,
    pre-tool, post-tool)
  - https://github.com/google/adk-samples/tree/main/python/agents/safety-plugins
  - CaMeL: security policy enforcement before each tool call
  - https://github.com/google/adk-samples/tree/main/python/agents/camel
  - AI Security Agent: Red Team -> Target -> Evaluator pipeline
  - https://github.com/google/adk-samples/tree/main/python/agents/ai-security-agent

Framework references:
  - OpenAI Agents SDK: Guardrails (input_guardrails, output_guardrails)
    https://openai.github.io/openai-agents-python/guardrails/
  - Google Cloud: safety considerations for agentic systems
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Deployment:
  - input_validator: safety classifier (PII detection, prompt injection)
  - core_agent: the actual LLM agent being protected
  - output_validator: output safety check (toxicity, compliance)
  - safe_fallback: generates a safe refusal response

Payload contract:
  state["user_input"]    - raw user input
  state["is_safe"]       - input safety flag (set by input_validator)
  state["response"]      - agent's response (set by core_agent)
  state["output_safe"]   - output safety flag (set by output_validator)
  state["violation_type"] - type of safety violation if any
"""


async def guardrails_sandwich(state: dict) -> dict:
    try:
        # Pre-processing: validate input safety
        state = await input_validator(state)

        # Core processing: the actual agent work
        state = await core_agent(state)

        # Post-processing: validate output safety
        state = await output_validator(state)

    except:
        # Safety violation caught: generate safe response
        state = await safe_fallback(state)

    return state


# --- Handler stubs ---


async def input_validator(state: dict) -> dict:
    """Safety actor: validate input before processing.

    Checks for:
    - Prompt injection attempts
    - PII in input (masks or rejects)
    - Content policy violations
    - Jailbreak patterns

    Raises RuntimeError on violation (caught by try/except router).
    On success, sets state["is_safe"] = True.
    """
    return state


async def core_agent(state: dict) -> dict:
    """LLM actor: the actual agent being protected.

    This is the "real" agent that does useful work. It only receives
    input that passed the input validator. Its output will be checked
    by the output validator before reaching the user.
    """
    return state


async def output_validator(state: dict) -> dict:
    """Safety actor: validate output before returning to user.

    Checks for:
    - Toxic or harmful content
    - Leaked system prompts or internal data
    - Compliance violations (financial advice, medical claims)
    - Hallucinated PII

    Raises RuntimeError on violation (caught by try/except router).
    On success, sets state["output_safe"] = True.
    """
    return state


async def safe_fallback(state: dict) -> dict:
    """Safety actor: generate a safe refusal response.

    Called when either validator catches a violation. Produces a
    polite, informative refusal that doesn't reveal what specific
    safety check was triggered.
    """
    return state
