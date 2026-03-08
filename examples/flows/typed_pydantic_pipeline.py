"""
Pydantic pipeline with the adapter pattern.

Three-layer structure:
  1. Domain:   pydantic models + typed business logic functions
  2. Adapters: actor handlers that bridge dict protocol to domain types
  3. Flow:     routing definition compiled to router actors

The adapter layer is the only place that touches `state: dict`.
Domain functions are plain Python — testable without any Asya runtime.

Serialization path:
  domain fn returns BaseModel -> stored in state -> _json_default ->
  model_dump(mode='json') -> JSON forwarded to next actor

Pattern: ingester -> scorer -> ranker -> responder

Payload contract:
  state["query"]      - search query string (input)
  state["top_k"]      - max candidates to retrieve (optional, default 10)
  state["candidates"] - list[Candidate] (set by ingester)
  state["scores"]     - list[ScoredCandidate] (set by scorer)
  state["ranked"]     - RankedResults (set by ranker)
  state["response"]   - SearchResponse (set by responder)
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
# Domain: business logic — pure Python, no Asya protocol
# Testable standalone: call directly in pytest, no runtime needed.
# =============================================================================


def retrieve(query: str, top_k: int = 10) -> list[Candidate]:
    """Fetch candidate documents for the query from the vector store.

    In production: calls an embedding model + vector DB (Pinecone, pgvector...).
    Returns up to `top_k` nearest-neighbour documents as typed Candidates.

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
    """Compute relevance and freshness scores for each candidate.

    In production: calls an embedding model to compute cosine similarity
    between the query and each candidate, plus a recency decay function.

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
    """Sort scored candidates by final_score descending.

    In production: may apply MMR (Maximum Marginal Relevance) or other
    diversity-aware re-ranking before returning the final ordered list.
    """
    sorted_scores = sorted(scores, key=lambda s: s.final_score, reverse=True)
    return RankedResults(query=query, results=sorted_scores, total=len(sorted_scores))


def generate_response(ranked: RankedResults) -> SearchResponse:
    """Wrap ranked results in a typed API response envelope.

    UUID request_id and datetime generated_at are serialized to strings
    automatically by model_dump(mode='json') inside _json_default.
    """
    return SearchResponse(
        request_id=uuid4(),
        ranked=ranked,
        generated_at=datetime.now(timezone.utc),
    )


# =============================================================================
# Actor adapters (handlers) — deploy each function as a separate AsyncActor
# =============================================================================
# Pattern per adapter: extract from state → call domain fn → merge result back.
# Adapters are the only layer that touches `state: dict`.
# Domain results are stored as typed objects; the runtime serializes them
# automatically when forwarding the envelope to the next actor.
# =============================================================================


def ingester(state: dict) -> dict:
    state["candidates"] = retrieve(state["query"], state.get("top_k", 10))
    return state


def scorer(state: dict) -> dict:
    state["scores"] = score(state["query"], state["candidates"])
    return state


def ranker(state: dict) -> dict:
    state["ranked"] = rank(state["query"], state["scores"])
    return state


def responder(state: dict) -> dict:
    state["response"] = generate_response(state["ranked"])
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
