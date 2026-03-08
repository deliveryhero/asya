"""
RAG Pipeline (Adaptive) - retrieve, evaluate, re-query, then generate.

Goes beyond basic RAG by adding an evaluation step after retrieval: if the
retrieved documents are insufficient, the agent refines its search query
and retries before generating the final answer.

Pattern: analyze_query -> while insufficient -> retrieve -> evaluate -> refine; -> generate

ADK equivalent:
  - RAG sample: VertexAiRagRetrieval with autonomous retrieval decisions
  - https://github.com/google/adk-samples/tree/main/python/agents/rag
  - Software Bug Assistant: multi-source retrieval (PostgreSQL, GitHub,
    StackOverflow, RAG vector search)
  - https://github.com/google/adk-samples/tree/main/python/agents/software-bug-assistant

Framework references:
  - LangGraph Adaptive RAG tutorial
    https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_adaptive_rag/
  - LangGraph Corrective RAG (CRAG)
    https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_crag/
  - LangGraph Self-RAG
    https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_self_rag/
  - LlamaIndex RAG workflows
    https://docs.llamaindex.ai/en/stable/understanding/rag/

Deployment:
  - query_analyzer: decomposes query, decides retrieval strategy
  - retriever: searches vector store / knowledge base
  - relevance_evaluator: judges if retrieved docs answer the query
  - query_refiner: rewrites query for better retrieval
  - generator: produces answer grounded in retrieved context
  - fact_checker: optional post-generation verification

Typed actors:
  Actor handlers return dataclasses directly — the Asya runtime serializes
  them automatically. Works identically with pydantic BaseModel.

Payload contract:
  state["question"]      - user's question
  state["query"]         - current search query (may differ from question)
  state["documents"]     - list[Document] (set by retriever)
  state["is_sufficient"] - bool (set by evaluator)
  state["answer"]        - GeneratedAnswer (set by generator)
"""

from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Typed result models
# ---------------------------------------------------------------------------


@dataclass
class QueryAnalysis:
    query: str
    key_concepts: List[str]
    strategy: str


@dataclass
class Document:
    content: str
    source: str
    relevance_score: float


@dataclass
class RelevanceEvaluation:
    is_sufficient: bool
    avg_score: float
    reasoning: str


@dataclass
class Citation:
    index: int
    source: str
    claim: str


@dataclass
class GeneratedAnswer:
    text: str
    citations: List[Citation]
    verified: bool = False


# ---------------------------------------------------------------------------
# Flow definition
# ---------------------------------------------------------------------------


async def rag_pipeline(state: dict) -> dict:
    state["retrieval_attempts"] = 0

    # Analyze query: decompose, identify key concepts
    analysis = await query_analyzer(state)
    state["query"] = analysis.query
    state["key_concepts"] = analysis.key_concepts

    # Adaptive retrieval loop
    while True:
        state["retrieval_attempts"] += 1

        # Retrieve documents — actor returns typed list
        state["documents"] = await retriever(state)

        # Evaluate relevance — actor returns typed evaluation
        evaluation = await relevance_evaluator(state)
        state["is_sufficient"] = evaluation.is_sufficient

        if evaluation.is_sufficient:
            break
        if state["retrieval_attempts"] >= 3:
            break

        state["query"] = await query_refiner(state)

    # Generate and verify answer — actor returns typed result
    state["answer"] = await generator(state)
    state["answer"] = await fact_checker(state)

    return state


# ---------------------------------------------------------------------------
# Handler stubs
# ---------------------------------------------------------------------------


async def query_analyzer(payload: dict) -> QueryAnalysis:
    """LLM actor: analyze and decompose the user's question.

    Returns a QueryAnalysis dataclass — runtime serializes it automatically.
    """
    question = payload["question"]
    return QueryAnalysis(
        query=f"semantic search: {question}",
        key_concepts=["machine learning", "neural networks", "training data", "model architecture"],
        strategy="semantic",
    )


async def retriever(payload: dict) -> List[Document]:
    """Tool actor: search knowledge base for relevant documents.

    Returns a list of Document dataclasses. Lists of dataclasses are
    serialized recursively by dataclasses.asdict().
    """
    attempt = payload.get("retrieval_attempts", 0)

    if attempt == 1:
        return [
            Document(
                content="Neural networks are computational models inspired by biological neurons.",
                source="ml_textbook_ch3.pdf",
                relevance_score=0.62,
            ),
            Document(
                content="Machine learning encompasses supervised and unsupervised approaches.",
                source="ai_overview.pdf",
                relevance_score=0.58,
            ),
        ]

    return [
        Document(
            content="Training data quality directly impacts neural network performance. "
            "Datasets should be representative, balanced, and sufficiently large.",
            source="deep_learning_practice.pdf",
            relevance_score=0.89,
        ),
        Document(
            content="Common neural network architectures include CNNs for image processing, "
            "RNNs for sequential data, and Transformers for language tasks.",
            source="architecture_guide.pdf",
            relevance_score=0.91,
        ),
        Document(
            content="Model training requires careful hyperparameter tuning including "
            "learning rate, batch size, and regularization parameters.",
            source="optimization_handbook.pdf",
            relevance_score=0.87,
        ),
    ]


async def relevance_evaluator(payload: dict) -> RelevanceEvaluation:
    """LLM actor: judge whether retrieved documents are sufficient.

    Returns a typed RelevanceEvaluation — the flow reads .is_sufficient directly.
    """
    documents = payload.get("documents", [])

    def _score(d):
        return d["relevance_score"] if isinstance(d, dict) else d.relevance_score

    avg = sum(_score(d) for d in documents) / len(documents) if documents else 0.0
    sufficient = avg > 0.75

    return RelevanceEvaluation(
        is_sufficient=sufficient,
        avg_score=avg,
        reasoning="Average relevance score threshold: 0.75",
    )


async def query_refiner(payload: dict) -> str:
    """LLM actor: rewrite the search query for better retrieval.

    Returns a plain string — the new query. Strings are JSON-native.
    """
    key_concepts = payload.get("key_concepts", [])
    return f"detailed guide: {' '.join(key_concepts[:2])} best practices and implementation"


async def generator(payload: dict) -> GeneratedAnswer:
    """LLM actor: generate answer grounded in retrieved context.

    Returns a GeneratedAnswer with embedded Citation dataclasses.
    Nested dataclasses serialize recursively — no manual conversion.
    """
    return GeneratedAnswer(
        text=(
            "Neural networks require high-quality training data that is representative, "
            "balanced, and sufficiently large [1]. Common architectures include CNNs for images, "
            "RNNs for sequences, and Transformers for language tasks [2]. Training involves "
            "careful hyperparameter tuning of learning rate, batch size, and regularization [3]."
        ),
        citations=[
            Citation(index=1, source="deep_learning_practice.pdf", claim="training data quality"),
            Citation(index=2, source="architecture_guide.pdf", claim="network architectures"),
            Citation(index=3, source="optimization_handbook.pdf", claim="hyperparameter tuning"),
        ],
    )


async def fact_checker(payload: dict) -> GeneratedAnswer:
    """LLM actor: verify generated answer against source documents.

    Receives the GeneratedAnswer from state, marks it as verified.
    """
    answer = payload.get("answer", {})
    if isinstance(answer, dict):
        return GeneratedAnswer(
            text=answer.get("text", ""),
            citations=[Citation(**c) if isinstance(c, dict) else c for c in answer.get("citations", [])],
            verified=True,
        )
    # Already a GeneratedAnswer instance (in-process flow execution)
    answer.verified = True
    return answer
