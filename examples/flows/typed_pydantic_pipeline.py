"""
Pydantic pipeline with the adapter pattern — two worlds, one boundary.

                Domain world          |  Asya protocol world
                (pure Python)         |  (dict-in, dict-out)
                                      |
  retrieve() -> list[Candidate]       |
  score()    -> list[ScoredCandidate] |  ingester(state: dict) -> dict
  rank()     -> RankedResults         |  scorer(state: dict) -> dict
  generate() -> SearchResponse        |  ranker(state: dict) -> dict
                                      |  responder(state: dict) -> dict

Domain functions are typed end-to-end. They never touch `state: dict`.
Adapters are the only code that knows about the dict protocol:
  1. Extract raw values from state dict
  2. Reconstruct typed objects via model_validate (validates + coerces)
  3. Call the domain function with typed arguments
  4. Store the typed result back — the runtime serializes it automatically

Why model_validate in adapters matters:
  After a queue hop, state["candidates"] is a list of plain dicts, not
  Candidate objects. model_validate reconstructs the typed model from
  the dict, raising ValidationError on malformed input rather than
  letting an AttributeError surface deep in domain code.

Serialization path (outbound):
  domain fn returns BaseModel -> stored in state -> _json_default ->
  model_dump(mode='json') -> JSON forwarded to next actor

Payload contract:
  state["query"]      - search query string (input)
  state["top_k"]      - max candidates to retrieve (optional, default 10)
  state["candidates"] - list[Candidate] serialized as list[dict] on wire
  state["scores"]     - list[ScoredCandidate] serialized as list[dict] on wire
  state["ranked"]     - RankedResults serialized as dict on wire
  state["response"]   - SearchResponse serialized as dict on wire
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel


# =============================================================================
# Domain: pydantic models
# =============================================================================


class Candidate(BaseModel):
    id: UUID
    text: str
    source: str
    created_at: datetime


class ScoredCandidate(BaseModel):
    candidate: Candidate
    relevance: float
    freshness: float

    @property
    def final_score(self) -> float:
        return self.relevance * 0.7 + self.freshness * 0.3


class RankedResults(BaseModel):
    query: str
    results: list[ScoredCandidate]
    total: int


class SearchResponse(BaseModel):
    request_id: UUID
    ranked: RankedResults
    generated_at: datetime


# =============================================================================
# Domain: business logic — pure Python, fully typed, no Asya protocol
#
# These functions know nothing about state dicts. They receive typed objects
# and return typed objects. Test them directly in pytest — no runtime needed.
# =============================================================================


def retrieve(query: str, top_k: int = 10) -> list[Candidate]:
    """Fetch candidate documents for the query from the vector store.

    In production: calls an embedding model + vector DB.

    Example production implementation:
        async def retrieve(query: str, top_k: int = 10) -> list[Candidate]:
            hits = await vector_store.search(query, top_k=top_k)
            return [
                Candidate(id=h.id, text=h.text, source=h.source,
                          created_at=h.timestamp)
                for h in hits
            ]
    """
    now = datetime.now(timezone.utc)
    docs = [
        ("Actor mesh enables event-driven AI workloads on Kubernetes.", "docs/architecture.md"),
        ("KEDA autoscaling allows scale-to-zero for idle actors.", "docs/scaling.md"),
        ("Envelope passing routes messages between actors via queues.", "docs/protocol.md"),
        ("The sidecar injects into actor pods via a mutating webhook.", "docs/injector.md"),
        ("Crossplane compositions manage queue lifecycle declaratively.", "docs/crossplane.md"),
    ]
    return [
        Candidate(id=uuid4(), text=text, source=src, created_at=now)
        for text, src in docs[:top_k]
    ]


def score(query: str, candidates: list[Candidate]) -> list[ScoredCandidate]:
    """Score each candidate for relevance and freshness against the query.

    In production: cosine similarity between query embedding and candidate
    embeddings, plus a recency decay function on created_at.

    Example production implementation:
        async def score(query: str, candidates: list[Candidate]) -> list[ScoredCandidate]:
            q_emb = await embed(query)
            return [
                ScoredCandidate(
                    candidate=c,
                    relevance=cosine_similarity(q_emb, await embed(c.text)),
                    freshness=recency_decay(c.created_at),
                )
                for c in candidates
            ]
    """
    return [
        ScoredCandidate(
            candidate=c,
            relevance=0.95 - i * 0.08,
            freshness=0.90 - i * 0.05,
        )
        for i, c in enumerate(candidates)
    ]


def rank(query: str, scores: list[ScoredCandidate]) -> RankedResults:
    """Sort scored candidates by final_score descending and return results.

    In production: may apply MMR (Maximum Marginal Relevance) for diversity.
    """
    sorted_scores = sorted(scores, key=lambda s: s.final_score, reverse=True)
    return RankedResults(query=query, results=sorted_scores, total=len(sorted_scores))


def generate_response(ranked: RankedResults) -> SearchResponse:
    """Wrap ranked results in a typed API response envelope."""
    return SearchResponse(
        request_id=uuid4(),
        ranked=ranked,
        generated_at=datetime.now(timezone.utc),
    )


# =============================================================================
# Actor adapters — deploy each as a separate AsyncActor
#
# Adapters are the only code that touches state: dict. Each adapter:
#   1. Extracts raw values from the incoming state dict
#   2. Reconstructs typed objects via model_validate (validates, raises on error)
#   3. Calls the domain function with typed arguments
#   4. Stores the typed result — the runtime serializes it on forward
#
# State values from previous actors always arrive as plain dicts (after JSON
# deserialization). model_validate bridges the dict → typed object gap.
# =============================================================================


def ingester(state: dict) -> dict:
    # Extract primitives, call domain fn, store typed result (serialized on forward)
    state["candidates"] = retrieve(state["query"], state.get("top_k", 10))
    return state


def scorer(state: dict) -> dict:
    # state["candidates"] arrives as list[dict] after the JSON boundary —
    # model_validate reconstructs Candidate objects before calling domain fn
    state["scores"] = score(
        state["query"],
        [Candidate.model_validate(c) for c in state["candidates"]],
    )
    return state


def ranker(state: dict) -> dict:
    # state["scores"] arrives as list[dict] — reconstruct ScoredCandidate objects
    state["ranked"] = rank(
        state["query"],
        [ScoredCandidate.model_validate(s) for s in state["scores"]],
    )
    return state


def responder(state: dict) -> dict:
    # state["ranked"] arrives as plain dict — reconstruct nested RankedResults
    state["response"] = generate_response(RankedResults.model_validate(state["ranked"]))
    return state


# =============================================================================
# Flow definition (compiled to router actors by `asya flow compile`)
# =============================================================================


def typed_pydantic_pipeline(p: dict) -> dict:
    p = ingester(p)
    p = scorer(p)
    p = ranker(p)
    p = responder(p)
    return p
