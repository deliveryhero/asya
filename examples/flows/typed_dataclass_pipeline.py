"""
Typed dataclass pipeline — actors return @dataclass objects directly.

Demonstrates that Asya actors can return stdlib dataclasses instead of
plain dicts. The runtime serializes them automatically via dataclasses.asdict()
— no manual dict conversion needed.

Serialization path:
  actor returns @dataclass -> _json_default -> dataclasses.asdict() -> JSON

Pattern: extractor -> classifier -> enricher -> formatter

Payload contract:
  p["text"]           - raw input text
  p["entities"]       - list of EntitySpan (set by extractor)
  p["label"]          - classification label (set by classifier)
  p["confidence"]     - classification confidence (set by classifier)
  p["enriched"]       - EnrichedData with metadata (set by enricher)
  p["result"]         - FormattedResult with final output (set by formatter)
"""

from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Typed result models — swap with pydantic BaseModel for identical behavior
# ---------------------------------------------------------------------------


@dataclass
class EntitySpan:
    text: str
    label: str
    start: int
    end: int
    confidence: float


@dataclass
class ClassificationResult:
    label: str
    confidence: float
    scores: dict


@dataclass
class EnrichedData:
    entity_count: int
    dominant_label: str
    metadata: dict


@dataclass
class FormattedResult:
    summary: str
    entities: List[EntitySpan]
    classification: ClassificationResult
    enriched: EnrichedData


# ---------------------------------------------------------------------------
# Flow definition (compiled to router actors)
# ---------------------------------------------------------------------------


def typed_dataclass_pipeline(p: dict) -> dict:
    p = extractor(p)
    p = classifier(p)
    p = enricher(p)
    p = formatter(p)
    return p


# ---------------------------------------------------------------------------
# Handler stubs (deployed as individual AsyncActors)
# ---------------------------------------------------------------------------


def extractor(p: dict) -> dict:
    """NER actor: extract entity spans from input text.

    Returns the state dict with p["entities"] set to a list of EntitySpan
    dataclasses. The runtime serializes the list recursively — no manual
    conversion needed.

    Example actor implementation:
        async def extractor(payload: dict) -> dict:
            spans = model.ner(payload["text"])
            payload["entities"] = [
                EntitySpan(text=s.text, label=s.label, start=s.start,
                           end=s.end, confidence=s.score)
                for s in spans
            ]
            return payload
    """
    p["entities"] = [
        EntitySpan(text="Asya", label="PRODUCT", start=0, end=4, confidence=0.98),
        EntitySpan(text="Kubernetes", label="TECHNOLOGY", start=22, end=32, confidence=0.95),
    ]
    return p


def classifier(p: dict) -> dict:
    """Classification actor: categorize the input text.

    Returns the state dict with p["label"] (str), p["confidence"] (float),
    and p["scores"] (ClassificationResult dataclass).

    Example actor implementation:
        async def classifier(payload: dict) -> dict:
            result = model.classify(payload["text"])
            payload["scores"] = ClassificationResult(
                label=result.top_label,
                confidence=result.top_score,
                scores=result.all_scores,
            )
            payload["label"] = result.top_label
            payload["confidence"] = result.top_score
            return payload
    """
    p["scores"] = ClassificationResult(
        label="technical",
        confidence=0.91,
        scores={"technical": 0.91, "general": 0.06, "marketing": 0.03},
    )
    p["label"] = "technical"
    p["confidence"] = 0.91
    return p


def enricher(p: dict) -> dict:
    """Enrichment actor: add metadata derived from prior results.

    Reads p["entities"] and p["label"]. Stores p["enriched"] as an
    EnrichedData dataclass — nested inside the state dict.

    Example actor implementation:
        async def enricher(payload: dict) -> dict:
            entities = payload.get("entities", [])
            payload["enriched"] = EnrichedData(
                entity_count=len(entities),
                dominant_label=payload.get("label", "unknown"),
                metadata={"source": "internal_ner_v2"},
            )
            return payload
    """
    entities = p.get("entities", [])
    p["enriched"] = EnrichedData(
        entity_count=len(entities),
        dominant_label=p.get("label", "unknown"),
        metadata={"source": "internal_ner_v2", "pipeline_version": "1.0"},
    )
    return p


def formatter(p: dict) -> dict:
    """Formatting actor: produce the final structured result.

    Assembles all prior typed results into a single FormattedResult
    dataclass at p["result"]. Demonstrates nested dataclass serialization:
    FormattedResult contains EntitySpan list and ClassificationResult.

    Example actor implementation:
        async def formatter(payload: dict) -> dict:
            payload["result"] = FormattedResult(
                summary=f"Found {len(payload['entities'])} entities, "
                        f"classified as {payload['label']}",
                entities=payload["entities"],
                classification=payload["scores"],
                enriched=payload["enriched"],
            )
            return payload
    """
    entities = p.get("entities", [])
    p["result"] = FormattedResult(
        summary=f"Found {len(entities)} entities, classified as {p.get('label', 'unknown')}",
        entities=entities,
        classification=p.get("scores", ClassificationResult("unknown", 0.0, {})),
        enriched=p.get("enriched", EnrichedData(0, "unknown", {})),
    )
    return p
