"""
Pydantic pipeline — actors return pydantic BaseModel instances directly.

Demonstrates that actors can return pydantic models without calling
.model_dump() manually. The runtime's _json_default hook calls
model.model_dump(mode='json') automatically, which:
  - Recursively converts nested models
  - Converts datetime/UUID/Decimal to JSON-native types (mode='json')
  - Works identically with pydantic v1 (.dict() + __fields__)

Serialization path:
  actor returns BaseModel -> _json_default -> model_dump(mode='json') -> JSON

Pattern: ingester -> scorer -> ranker -> responder

Payload contract:
  p["query"]       - search query string
  p["candidates"]  - list of Candidate models (set by ingester)
  p["scores"]      - list of ScoredCandidate models (set by scorer)
  p["ranked"]      - RankedResults model (set by ranker)
  p["response"]    - SearchResponse model (set by responder)

Note:
  This example uses duck-typing to work without pydantic installed.
  Replace the stub classes with real pydantic BaseModel subclasses
  in actual deployments — no other changes needed.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

# ---------------------------------------------------------------------------
# Pydantic models (replace with `from pydantic import BaseModel` in prod)
# Duck-typed stubs that implement the model_dump() protocol — identical
# serialization behavior, no pydantic dependency for running this example.
# ---------------------------------------------------------------------------


class _BaseModel:
    """Minimal duck-typed BaseModel stub. In production, use pydantic.BaseModel."""

    def model_dump(self, mode=None):
        result = {}
        for key, val in self.__dict__.items():
            if key.startswith("_"):
                continue
            if mode == "json":
                if isinstance(val, datetime):
                    result[key] = val.isoformat()
                elif isinstance(val, UUID):
                    result[key] = str(val)
                elif isinstance(val, list):
                    result[key] = [
                        v.model_dump(mode="json") if hasattr(v, "model_dump") else v
                        for v in val
                    ]
                elif hasattr(val, "model_dump"):
                    result[key] = val.model_dump(mode="json")
                else:
                    result[key] = val
            else:
                result[key] = val
        return result


class Candidate(_BaseModel):
    def __init__(self, id: UUID, text: str, source: str, created_at: datetime):
        self.id = id
        self.text = text
        self.source = source
        self.created_at = created_at


class ScoredCandidate(_BaseModel):
    def __init__(self, candidate: Candidate, relevance: float, freshness: float):
        self.candidate = candidate
        self.relevance = relevance
        self.freshness = freshness

    @property
    def final_score(self) -> float:
        return self.relevance * 0.7 + self.freshness * 0.3


class RankedResults(_BaseModel):
    def __init__(self, query: str, results: list, total: int):
        self.query = query
        self.results = results
        self.total = total


class SearchResponse(_BaseModel):
    def __init__(self, request_id: UUID, ranked: RankedResults, generated_at: datetime):
        self.request_id = request_id
        self.ranked = ranked
        self.generated_at = generated_at


# ---------------------------------------------------------------------------
# Flow definition (compiled to router actors)
# ---------------------------------------------------------------------------


def pydantic_pipeline(p: dict) -> dict:
    p = ingester(p)
    p = scorer(p)
    p = ranker(p)
    p = responder(p)
    return p


# ---------------------------------------------------------------------------
# Handler stubs (deployed as individual AsyncActors)
# ---------------------------------------------------------------------------


def ingester(p: dict) -> dict:
    """Retrieval actor: fetch candidate documents for the query.

    Returns p["candidates"] as a list of Candidate pydantic models.
    Note datetime and UUID fields — model_dump(mode='json') converts them
    to ISO-8601 string and UUID string respectively.

    Example actor implementation (real pydantic):
        from pydantic import BaseModel
        from datetime import datetime, timezone
        from uuid import UUID, uuid4

        class Candidate(BaseModel):
            id: UUID
            text: str
            source: str
            created_at: datetime

        async def ingester(payload: dict) -> dict:
            docs = await vector_store.search(payload["query"], top_k=10)
            payload["candidates"] = [
                Candidate(
                    id=uuid4(),
                    text=doc.content,
                    source=doc.source,
                    created_at=doc.timestamp,
                )
                for doc in docs
            ]
            return payload
    """
    now = datetime.now(timezone.utc)
    p["candidates"] = [
        Candidate(
            id=uuid4(),
            text="Actor mesh enables event-driven AI workloads on Kubernetes.",
            source="docs/architecture.md",
            created_at=now,
        ),
        Candidate(
            id=uuid4(),
            text="KEDA autoscaling allows scale-to-zero for idle actors.",
            source="docs/scaling.md",
            created_at=now,
        ),
        Candidate(
            id=uuid4(),
            text="Envelope passing routes messages between actors via queues.",
            source="docs/protocol.md",
            created_at=now,
        ),
    ]
    return p


def scorer(p: dict) -> dict:
    """Scoring actor: compute relevance and freshness scores.

    Reads p["candidates"] (list of Candidate or dict). Returns
    p["scores"] as a list of ScoredCandidate models. Nested models
    (ScoredCandidate containing Candidate) serialize recursively.

    Example actor implementation:
        async def scorer(payload: dict) -> dict:
            query = payload["query"]
            payload["scores"] = [
                ScoredCandidate(
                    candidate=c,
                    relevance=await embed_model.similarity(query, c.text),
                    freshness=compute_freshness(c.created_at),
                )
                for c in payload["candidates"]
            ]
            return payload
    """
    candidates = p.get("candidates", [])
    p["scores"] = [
        ScoredCandidate(candidate=c, relevance=0.85 - i * 0.1, freshness=0.9 - i * 0.05)
        for i, c in enumerate(candidates)
    ]
    return p


def ranker(p: dict) -> dict:
    """Ranking actor: sort scored candidates by final score.

    Returns p["ranked"] as a RankedResults pydantic model containing
    the sorted list. Demonstrates that list fields with nested models
    serialize recursively without any manual conversion.

    Example actor implementation:
        async def ranker(payload: dict) -> dict:
            scored = payload["scores"]
            sorted_results = sorted(scored, key=lambda s: s.final_score, reverse=True)
            payload["ranked"] = RankedResults(
                query=payload["query"],
                results=sorted_results,
                total=len(sorted_results),
            )
            return payload
    """
    scores = p.get("scores", [])
    sorted_scores = sorted(scores, key=lambda s: s.relevance, reverse=True)
    p["ranked"] = RankedResults(
        query=p.get("query", ""),
        results=sorted_scores,
        total=len(sorted_scores),
    )
    return p


def responder(p: dict) -> dict:
    """Response actor: wrap ranked results in a typed API response.

    Returns p["response"] as a SearchResponse model with UUID request_id
    and datetime generated_at. model_dump(mode='json') converts both to
    strings automatically.

    Example actor implementation:
        async def responder(payload: dict) -> dict:
            payload["response"] = SearchResponse(
                request_id=uuid4(),
                ranked=payload["ranked"],
                generated_at=datetime.now(timezone.utc),
            )
            return payload
    """
    p["response"] = SearchResponse(
        request_id=uuid4(),
        ranked=p.get("ranked", RankedResults("", [], 0)),
        generated_at=datetime.now(timezone.utc),
    )
    return p
