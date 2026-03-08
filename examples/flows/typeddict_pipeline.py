"""
TypedDict pipeline — actors return TypedDict for zero-overhead schema clarity.

TypedDicts are plain Python dicts at runtime — isinstance(td, dict) is True.
The runtime sends them through json.dumps without calling _json_default at all.
Use TypedDict when you want schema documentation + IDE completion without
any serialization overhead.

Serialization path:
  actor returns TypedDict -> json.dumps (native, no hook needed) -> JSON

Pattern: parser -> validator -> transformer -> sink_adapter

Payload contract:
  p["raw"]         - raw input bytes or string
  p["parsed"]      - ParsedDoc TypedDict (set by parser)
  p["validation"]  - ValidationResult TypedDict (set by validator)
  p["transformed"] - TransformedDoc TypedDict (set by transformer)
  p["output"]      - SinkPayload TypedDict (set by sink_adapter)
"""

from typing import List, TypedDict


# ---------------------------------------------------------------------------
# TypedDict schemas — plain dicts with type annotations
# ---------------------------------------------------------------------------


class Section(TypedDict):
    heading: str
    body: str
    word_count: int


class ParsedDoc(TypedDict):
    title: str
    sections: List[Section]
    author: str
    language: str


class ValidationResult(TypedDict):
    valid: bool
    errors: List[str]
    warnings: List[str]
    section_count: int


class TransformedDoc(TypedDict):
    title: str
    content: str
    summary: str
    word_count: int
    language: str


class SinkPayload(TypedDict):
    id: str
    data: TransformedDoc
    schema_version: str
    ready: bool


# ---------------------------------------------------------------------------
# Flow definition (compiled to router actors)
# ---------------------------------------------------------------------------


def typeddict_pipeline(p: dict) -> dict:
    p = parser(p)
    p = validator(p)
    if not p.get("valid", True):
        p = error_handler(p)
        return p
    p = transformer(p)
    p = sink_adapter(p)
    return p


# ---------------------------------------------------------------------------
# Handler stubs (deployed as individual AsyncActors)
# ---------------------------------------------------------------------------


def parser(p: dict) -> dict:
    """Parsing actor: convert raw input to structured ParsedDoc TypedDict.

    TypedDicts are identical to plain dicts at runtime — no serialization
    overhead. Use them for self-documenting payload schemas.

    Example actor implementation:
        async def parser(payload: dict) -> dict:
            doc: ParsedDoc = {
                "title": extract_title(payload["raw"]),
                "sections": [
                    {"heading": s.heading, "body": s.body,
                     "word_count": len(s.body.split())}
                    for s in split_sections(payload["raw"])
                ],
                "author": extract_author(payload["raw"]),
                "language": detect_language(payload["raw"]),
            }
            payload["parsed"] = doc
            return payload
    """
    doc: ParsedDoc = {
        "title": "Introduction to Actor Mesh",
        "sections": [
            {"heading": "Overview", "body": "Actor mesh enables...", "word_count": 3},
            {"heading": "Architecture", "body": "Built on Kubernetes...", "word_count": 3},
        ],
        "author": "Asya Team",
        "language": "en",
    }
    p["parsed"] = doc
    return p


def validator(p: dict) -> dict:
    """Validation actor: check parsed document against schema rules.

    Returns ValidationResult TypedDict in p["validation"] and flattens
    p["valid"] for routing decisions in the flow.

    Example actor implementation:
        async def validator(payload: dict) -> dict:
            parsed = payload["parsed"]
            errors = []
            if not parsed.get("title"):
                errors.append("missing title")
            if not parsed.get("sections"):
                errors.append("no sections found")
            result: ValidationResult = {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": [],
                "section_count": len(parsed.get("sections", [])),
            }
            payload["validation"] = result
            payload["valid"] = result["valid"]
            return payload
    """
    parsed = p.get("parsed", {})
    sections = parsed.get("sections", [])
    errors = [] if parsed.get("title") and sections else ["missing content"]
    result: ValidationResult = {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": [],
        "section_count": len(sections),
    }
    p["validation"] = result
    p["valid"] = result["valid"]
    return p


def error_handler(p: dict) -> dict:
    """Error actor: handle invalid documents."""
    p["error"] = f"Validation failed: {p.get('validation', {}).get('errors', [])}"
    return p


def transformer(p: dict) -> dict:
    """Transform actor: flatten parsed sections into a single document.

    Example actor implementation:
        async def transformer(payload: dict) -> dict:
            parsed = payload["parsed"]
            content = "\\n\\n".join(
                f"## {s['heading']}\\n{s['body']}"
                for s in parsed["sections"]
            )
            transformed: TransformedDoc = {
                "title": parsed["title"],
                "content": content,
                "summary": content[:200],
                "word_count": sum(s["word_count"] for s in parsed["sections"]),
                "language": parsed["language"],
            }
            payload["transformed"] = transformed
            return payload
    """
    parsed = p.get("parsed", {})
    sections = parsed.get("sections", [])
    content = "\n\n".join(f"## {s['heading']}\n{s['body']}" for s in sections)
    transformed: TransformedDoc = {
        "title": parsed.get("title", ""),
        "content": content,
        "summary": content[:200],
        "word_count": sum(s.get("word_count", 0) for s in sections),
        "language": parsed.get("language", "en"),
    }
    p["transformed"] = transformed
    return p


def sink_adapter(p: dict) -> dict:
    """Sink adapter actor: wrap transformed document for downstream consumption.

    Example actor implementation:
        async def sink_adapter(payload: dict) -> dict:
            import uuid
            payload["output"] = SinkPayload(
                id=str(uuid.uuid4()),
                data=payload["transformed"],
                schema_version="2.0",
                ready=True,
            )
            return payload
    """
    output: SinkPayload = {
        "id": "doc-12345",
        "data": p.get("transformed", {}),
        "schema_version": "2.0",
        "ready": True,
    }
    p["output"] = output
    return p
