"""
Parallel Sectioning - independent subtasks dispatched concurrently.

Multiple specialized actors process the SAME input in parallel, each
extracting different aspects. An aggregator merges all results. This
reduces end-to-end latency proportionally to the number of parallel actors.

Pattern: fan-out [analyzer_A, analyzer_B, analyzer_C] -> aggregator

ADK equivalent:
  - ADK ParallelAgent: runs sub-agents concurrently within a session
  - Parallel Task Decomposition: broadcast findings to Slack+Gmail+Calendar
  - https://github.com/google/adk-samples/tree/main/python/agents/parallel-task-decomposition
  - Story Teller: parallel writers (Creative + Focused) generate competing drafts
  - https://github.com/google/adk-samples/tree/main/python/agents/story-teller

Framework references:
  - Anthropic "Parallelization (Sectioning)" pattern
    https://www.anthropic.com/engineering/building-effective-agents
  - LangGraph Send API for parallel dispatch
    https://langchain-ai.github.io/langgraph/how-tos/map-reduce/
  - Google Cloud "Multi-agent (parallel)" pattern
    https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Deployment:
  - preprocessor: prepare input for parallel analysis
  - sentiment_analyzer, topic_extractor, entity_recognizer: independent specialists
  - aggregator: merge all parallel results

Payload contract:
  state["text"]          - input text to analyze
  state["analysis"]      - list of parallel results (set by fan-out)
  state["merged_result"] - combined analysis (set by aggregator)
"""

import asyncio


async def parallel_sectioning(state: dict) -> dict:
    # Prepare input for parallel analysis
    state = await preprocessor(state)

    # Fan-out: three independent analyses run in parallel
    state["analysis"] = list(await asyncio.gather(
        sentiment_analyzer(state["text"]),
        topic_extractor(state["text"]),
        entity_recognizer(state["text"]),
    ))

    # Fan-in: merge all parallel results
    state = await aggregator(state)
    return state


# --- Handler stubs ---


async def preprocessor(state: dict) -> dict:
    """Actor: prepare input text for analysis.

    Normalizes text, handles encoding, truncates if needed.
    Sets state["text"] for downstream analyzers.
    """
    raw_text = state.get("raw_text") or state.get("text", "")
    cleaned = raw_text.strip().replace("\n\n", "\n")

    state["text"] = cleaned
    state["char_count"] = len(cleaned)
    state["word_count"] = len(cleaned.split())

    return state


async def sentiment_analyzer(text: dict) -> dict:
    """LLM/ML actor: analyze sentiment of the text.

    Returns {"sentiment": "positive|negative|neutral", "confidence": 0.95}
    """
    return {
        "sentiment": "positive",
        "confidence": 0.87,
        "highlights": [
            "innovative approach",
            "significant improvement",
            "promising results",
        ],
    }


async def topic_extractor(text: dict) -> dict:
    """LLM actor: extract main topics and themes.

    Returns {"topics": ["AI", "healthcare"], "keywords": [...]}
    """
    return {
        "topics": [
            "artificial intelligence",
            "healthcare technology",
            "diagnostic systems",
            "patient outcomes",
        ],
        "keywords": [
            "machine learning",
            "medical imaging",
            "clinical decision support",
            "accuracy",
            "efficiency",
        ],
    }


async def entity_recognizer(text: dict) -> dict:
    """ML actor: recognize named entities (people, orgs, locations).

    Returns {"entities": [{"text": "Google", "type": "ORG"}, ...]}
    """
    return {
        "entities": [
            {"text": "Stanford University", "type": "ORG"},
            {"text": "Dr. Sarah Chen", "type": "PERSON"},
            {"text": "Silicon Valley", "type": "LOC"},
            {"text": "Johns Hopkins Hospital", "type": "ORG"},
        ]
    }


async def aggregator(state: dict) -> dict:
    """Actor: merge parallel analysis results into a unified view.

    Reads state["analysis"] (list of results from parallel actors),
    combines them into state["merged_result"] with a coherent structure.
    """
    analysis = state["analysis"]

    sentiment_result = analysis[0]
    topic_result = analysis[1]
    entity_result = analysis[2]

    state["merged_result"] = {
        "sentiment": sentiment_result,
        "topics": topic_result,
        "entities": entity_result,
        "summary": f"Analyzed {state.get('word_count', 0)} words with {sentiment_result['sentiment']} sentiment, covering {len(topic_result['topics'])} main topics and identifying {len(entity_result['entities'])} named entities.",
    }

    return state
