# CrewAI Single Agent Example

This is a minimal working example of a single agent in CrewAI. It demonstrates the core concepts:
- Creating an Agent with role, goal, and backstory
- Defining custom tools using the `@tool` decorator
- Creating and executing a Task
- Running the agent through a Crew

## Example Overview

The example implements a **Product Review Analyst** agent that:
1. Analyzes sentiment of product reviews
2. Extracts relevant keywords
3. Summarizes the review

The agent has 3 mock tools (no external API calls required):
- `analyze_sentiment()` - Determines if review is positive, negative, or neutral
- `extract_keywords()` - Pulls out relevant keywords from the text
- `summarize_review()` - Creates a brief summary

## Setup

### 1. Install CrewAI

From the `crewai/` directory:

```bash
uv sync
```

Or with pip:

```bash
pip install -e .
```

### 2. Set up API Keys (Optional)

CrewAI defaults to using Claude via Anthropic's API. To use it, set your API key:

```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

If you prefer OpenAI:

```bash
export OPENAI_API_KEY="your-api-key-here"
```

**Note**: The example includes a sample review in the code, so you can run it without API keys if you just want to test the tool definitions and crew structure.

## Running the Example

From the `01-single-agent/` directory:

```bash
python agent.py
```

Or with uv:

```bash
uv run agent.py
```

## Expected Output

The agent will:
1. Receive the review analysis task
2. Use its tools to analyze the sample product review
3. Output a detailed analysis with sentiment, keywords, and summary

Example output structure:
```
==============================================================
ANALYSIS RESULT
==============================================================
[Agent's analysis of the review including sentiment classification,
extracted keywords, and a summary of the review]
```

## Code Structure

```python
# 1. Define tools with @tool decorator
@tool("Tool Name")
def tool_function(input: str) -> str:
    """Tool description"""
    return result

# 2. Create an agent
agent = Agent(
    role="Your Role",
    goal="Your Goal",
    backstory="Your Backstory",
    tools=[tool1, tool2, tool3],
    verbose=True,
)

# 3. Create a task
task = Task(
    description="What to do",
    expected_output="Expected format",
    agent=agent,
)

# 4. Create a crew and run it
crew = Crew(
    agents=[agent],
    tasks=[task],
    verbose=True,
)

result = crew.kickoff()
```

## Key Concepts

### Agent
An autonomous unit with:
- **role**: What the agent does (e.g., "Product Analyst")
- **goal**: What it aims to achieve
- **backstory**: Context and experience
- **tools**: Functions it can call to accomplish tasks

### Task
A specific job for an agent:
- **description**: What needs to be done
- **expected_output**: Format of the result
- **agent**: Which agent performs it

### Crew
A container for agents and tasks:
- Orchestrates agents
- Executes tasks sequentially
- `kickoff()` runs the crew

### Tools
Functions agents can call, decorated with `@tool()`:
- Parameter descriptions help the agent decide which tool to use
- Always return strings
- Can be async or sync

## Next Steps

1. **Modify the review**: Edit the `sample_review` string in `agent.py` to test with different inputs
2. **Add more tools**: Create additional `@tool` decorated functions for different capabilities
3. **Chain tasks**: Create multiple tasks for the agent to execute sequentially
4. **Multi-agent**: Check the companion examples for multi-agent architectures

## References

- [CrewAI Documentation](https://docs.crewai.com/)
- [Creating Custom Tools](https://docs.crewai.com/en/learn/create-custom-tools)
- [Agent Concepts](https://docs.crewai.com/en/concepts/agents)
