"""
Minimal DSPy single-agent example using ReAct pattern with tools.

DSPy is data-science-first: modules are composed of signatures (input/output specs)
and language model calls. Tools are defined as regular functions with docstrings.

This example demonstrates:
- Tool definition with docstrings and type hints
- ReAct module for reasoning and tool use
- Direct LM configuration (no orchestration framework)
"""

import dspy
import os
from typing import Optional

# Stub tool implementations (in production, these would call real APIs)

def search_knowledge_base(query: str) -> str:
    """
    Search a knowledge base for information about a query.

    Args:
        query: The search query

    Returns:
        Relevant information from the knowledge base
    """
    # Stub knowledge base
    knowledge_base = {
        "dspy": "DSPy is a framework for programming language models without prompting. It uses signatures for declarative task specification.",
        "python": "Python is a high-level programming language known for simplicity and readability.",
        "agents": "Agents are autonomous systems that perceive their environment and take actions to achieve goals.",
        "tools": "Tools extend agent capabilities by providing external functions and APIs.",
    }

    query_lower = query.lower()
    for key, value in knowledge_base.items():
        if key in query_lower:
            return value

    return f"No information found about '{query}' in knowledge base."


def calculate_math(expression: str) -> str:
    """
    Evaluate a simple mathematical expression.

    Args:
        expression: A mathematical expression to evaluate (e.g., "2 + 2")

    Returns:
        The result of the calculation
    """
    try:
        result = eval(expression)
        return f"Result: {result}"
    except Exception as e:
        return f"Error calculating '{expression}': {str(e)}"


def get_definition(term: str) -> str:
    """
    Get a definition for a technical term.

    Args:
        term: The term to define

    Returns:
        Definition of the term
    """
    definitions = {
        "signature": "In DSPy, a signature is a declarative specification of the input/output of a language model call.",
        "module": "A DSPy module is a reusable component that encapsulates language model calls and logic.",
        "react": "ReAct is a reasoning and acting pattern that allows agents to reason about which tools to use.",
    }

    term_lower = term.lower()
    for key, value in definitions.items():
        if key in term_lower:
            return value

    return f"No definition found for '{term}'."


class SingleAgentModule(dspy.Module):
    """
    A single agent using DSPy's ReAct pattern.

    ReAct automatically handles:
    - Reasoning about which tools to use
    - Tool invocation and result handling
    - Iterating until a final answer is reached
    """

    def __init__(self):
        super().__init__()

        # Define the ReAct agent with tools
        # Signature: Takes a question, produces an answer (reasoning is automatic)
        self.agent = dspy.ReAct(
            signature="question -> answer",
            tools=[search_knowledge_base, calculate_math, get_definition],
            max_iters=5,  # Maximum reasoning iterations
        )

    def forward(self, question: str) -> dspy.Prediction:
        """
        Process a question through the ReAct agent.

        Args:
            question: The question to answer

        Returns:
            A Prediction object with answer (and intermediate reasoning)
        """
        return self.agent(question=question)


def main():
    """
    Main entry point demonstrating the single-agent pattern.
    """
    # Configure DSPy with local LM (requires API key)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print(
            "Warning: OPENAI_API_KEY environment variable not set. "
            "Using mock instead."
        )
        print("\nExample with mock output:")
        print("=" * 60)
        demonstrate_with_stub()
        return

    # Configure with OpenAI
    dspy.configure(lm=dspy.LM("openai/gpt-4o-mini", cache=False))

    # Initialize the agent
    agent = SingleAgentModule()

    # Example questions
    questions = [
        "What is DSPy and how does it differ from other frameworks?",
        "Calculate 25 * 4 and tell me what it is",
        "Define what a module is in the context of DSPy",
    ]

    print("DSPy Single Agent (ReAct Pattern)")
    print("=" * 60)

    for question in questions:
        print(f"\nQuestion: {question}")
        print("-" * 60)

        try:
            result = agent.forward(question)
            print(f"Answer: {result.answer}")
            if hasattr(result, "reasoning") and result.reasoning:
                print(f"Reasoning: {result.reasoning}")
        except Exception as e:
            print(f"Error: {e}")

    print("\n" + "=" * 60)
    print("Agent completed processing all questions")


def demonstrate_with_stub():
    """
    Demonstrate agent behavior with mock output (no LM required).
    """
    print("\nExample Agent Behavior (Stub):")
    print("-" * 60)

    # Simulate tool calls
    print("\nSimulating: 'What is DSPy?'")
    result = search_knowledge_base("dspy")
    print(f"Tool: search_knowledge_base('dspy')")
    print(f"Result: {result}")

    print("\n" + "-" * 60)
    print("\nSimulating: 'Calculate 25 * 4'")
    result = calculate_math("25 * 4")
    print(f"Tool: calculate_math('25 * 4')")
    print(f"Result: {result}")

    print("\n" + "-" * 60)
    print("\nSimulating: 'Define module'")
    result = get_definition("module")
    print(f"Tool: get_definition('module')")
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
