"""
Async sequential flow - ADK LLM Auditor pattern.

Based on ADK SequentialAgent: a critic reviews LLM output,
then a reviser improves it based on critique. Demonstrates
async/await with sequential handler execution.

Reference: https://github.com/google/adk-samples/tree/main/python/agents/llm-auditor
"""


async def llm_auditor_flow(state: dict) -> dict:
    state = await critic(state)
    state = await reviser(state)
    return state


async def critic(state: dict) -> dict:
    """Critique LLM output for accuracy and completeness."""
    return state


async def reviser(state: dict) -> dict:
    """Revise output based on critic feedback."""
    return state
