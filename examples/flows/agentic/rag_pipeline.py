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

Payload contract:
  state["question"]     - user's question
  state["query"]        - current search query (may differ from question)
  state["documents"]    - retrieved documents
  state["is_sufficient"] - whether docs are sufficient (set by evaluator)
  state["answer"]       - generated answer
  state["citations"]    - source citations
"""


async def rag_pipeline(state: dict) -> dict:
    state["retrieval_attempts"] = 0

    # Analyze query: decompose, identify key concepts
    state = await query_analyzer(state)

    # Adaptive retrieval loop
    while True:
        state["retrieval_attempts"] += 1

        # Retrieve documents from knowledge base
        state = await retriever(state)

        # Evaluate relevance of retrieved documents
        state = await relevance_evaluator(state)

        # Sufficient context found
        if state.get("is_sufficient"):
            break

        # Max retrieval attempts reached
        if state["retrieval_attempts"] >= 3:
            break

        # Refine query for better results
        state = await query_refiner(state)

    # Generate answer grounded in retrieved context
    state = await generator(state)

    # Verify generated answer against sources
    state = await fact_checker(state)

    return state


# --- Handler stubs ---


async def query_analyzer(state: dict) -> dict:
    """LLM actor: analyze and decompose the user's question.

    Identifies key concepts, determines retrieval strategy (keyword vs
    semantic vs hybrid), and may decompose complex questions into
    sub-queries. Sets state["query"] for the retriever.
    """
    question = state["question"]
    state["query"] = f"semantic search: {question}"
    state["key_concepts"] = [
        "machine learning",
        "neural networks",
        "training data",
        "model architecture",
    ]
    return state


async def retriever(state: dict) -> dict:
    """Tool actor: search knowledge base for relevant documents.

    Executes state["query"] against a vector store, database, or
    search engine. Returns state["documents"] - a list of document
    chunks with metadata (source, relevance score, etc.).
    """
    query = state["query"]
    attempt = state.get("retrieval_attempts", 0)

    if attempt == 1:
        state["documents"] = [
            {
                "content": "Neural networks are computational models inspired by biological neurons.",
                "source": "ml_textbook_ch3.pdf",
                "relevance_score": 0.62,
            },
            {
                "content": "Machine learning encompasses supervised and unsupervised approaches.",
                "source": "ai_overview.pdf",
                "relevance_score": 0.58,
            },
        ]
    else:
        state["documents"] = [
            {
                "content": "Training data quality directly impacts neural network performance. Datasets should be representative, balanced, and sufficiently large.",
                "source": "deep_learning_practice.pdf",
                "relevance_score": 0.89,
            },
            {
                "content": "Common neural network architectures include CNNs for image processing, RNNs for sequential data, and Transformers for language tasks.",
                "source": "architecture_guide.pdf",
                "relevance_score": 0.91,
            },
            {
                "content": "Model training requires careful hyperparameter tuning including learning rate, batch size, and regularization parameters.",
                "source": "optimization_handbook.pdf",
                "relevance_score": 0.87,
            },
        ]
    return state


async def relevance_evaluator(state: dict) -> dict:
    """LLM actor: judge whether retrieved documents are sufficient.

    Evaluates state["documents"] against state["question"]. Sets
    state["is_sufficient"] to True if the documents contain enough
    information to answer the question. May also filter out
    irrelevant documents.
    """
    documents = state["documents"]
    question = state["question"]

    avg_relevance = sum(doc["relevance_score"] for doc in documents) / len(documents)
    state["is_sufficient"] = avg_relevance > 0.75

    return state


async def query_refiner(state: dict) -> dict:
    """LLM actor: rewrite the search query for better retrieval.

    Based on state["question"], state["documents"] (what was found),
    and what's missing, generates a refined state["query"] that
    targets the gaps.
    """
    question = state["question"]
    documents = state["documents"]
    key_concepts = state["key_concepts"]

    state["query"] = f"detailed guide: {' '.join(key_concepts[:2])} best practices and implementation"

    return state


async def generator(state: dict) -> dict:
    """LLM actor: generate answer grounded in retrieved context.

    Receives state["question"] and state["documents"]. Produces
    state["answer"] with inline citations. Must only use information
    from the provided documents (no hallucination).
    """
    question = state["question"]
    documents = state["documents"]

    state["answer"] = (
        "Neural networks require high-quality training data that is representative, "
        "balanced, and sufficiently large [1]. Common architectures include CNNs for images, "
        "RNNs for sequences, and Transformers for language tasks [2]. Training involves "
        "careful hyperparameter tuning of learning rate, batch size, and regularization [3]."
    )

    return state


async def fact_checker(state: dict) -> dict:
    """LLM actor: verify generated answer against source documents.

    Cross-references state["answer"] with state["documents"] to
    ensure all claims are supported. Flags unsupported claims and
    adds state["citations"] linking answer segments to source docs.
    """
    answer = state["answer"]
    documents = state["documents"]

    state["citations"] = [
        {"index": 1, "source": "deep_learning_practice.pdf", "claim": "training data quality"},
        {"index": 2, "source": "architecture_guide.pdf", "claim": "network architectures"},
        {"index": 3, "source": "optimization_handbook.pdf", "claim": "hyperparameter tuning"},
    ]
    state["verified"] = True

    return state
