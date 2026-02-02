"""
DSPy Single Agent with ReAct Pattern.

Demonstrates the ReAct (Reasoning + Acting) pattern where the LLM
reasons about which tools to use and iterates until it has an answer.
"""

import dspy


# Define tools as simple Python functions with docstrings
def search(query: str) -> str:
    """Search for information about a topic."""
    # In production, this would call a real search API
    data = {
        "dspy": "DSPy is a framework for programming language models declaratively.",
        "react": "ReAct combines reasoning and acting in language models.",
        "python": "Python is a high-level programming language.",
    }
    for key, value in data.items():
        if key in query.lower():
            return value
    return f"No results for: {query}"


def calculate(expression: str) -> str:
    """Evaluate a math expression."""
    try:
        return str(eval(expression))
    except Exception as e:
        return f"Error: {e}"


def main():
    # Configure the language model
    lm = dspy.LM("openai/gpt-4o-mini")
    dspy.configure(lm=lm)

    # Create a ReAct agent with tools
    agent = dspy.ReAct(
        signature="question -> answer",
        tools=[search, calculate],
    )

    # Run the agent
    questions = [
        "What is DSPy?",
        "What is 25 * 4?",
    ]

    for q in questions:
        print(f"\nQ: {q}")
        result = agent(question=q)
        print(f"A: {result.answer}")


if __name__ == "__main__":
    main()
