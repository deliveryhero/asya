"""
Complex workflow example.

Demonstrates nested control structures combining if/else and while loops.
"""


def complex_flow(p: dict) -> dict:
    p = handler_preprocess(p)
    p = handler_validate(p)

    if not p["valid"]:
        p = handler_error(p)
        return p

    if p.get("needs_enrichment"):
        p = handler_enrich_data(p)

        while p.get("batch_count", 0) < p.get("max_batches", 3):
            p = handler_transform_batch(p)
            p = handler_check_quality(p)

            if p["quality_score"] < 20:
                continue

            if p["quality_score"] >= 50:
                break
    else:
        if p.get("requires_retry"):
            p = handler_retry_handler(p)

    p = handler_finalize(p)
    return p


def handler_preprocess(p: dict) -> dict:
    """Initial preprocessing."""
    p["stage"] = "preprocessed"
    return p


def handler_validate(p: dict) -> dict:
    """Validate data."""
    p["valid"] = p.get("data") is not None
    return p


def handler_enrich_data(p: dict) -> dict:
    """Enrich data with additional information."""
    p["enriched"] = True
    return p


def handler_transform_batch(p: dict) -> dict:
    """Transform batch of items."""
    if "batch_count" not in p:
        p["batch_count"] = 0
    p["batch_count"] += 1
    return p


def handler_check_quality(p: dict) -> dict:
    """Check quality metrics."""
    p["quality_checked"] = True
    p["quality_score"] = p.get("batch_count", 0) * 10
    return p


def handler_retry_handler(p: dict) -> dict:
    """Handle retry logic."""
    p["retried"] = True
    if "retry_count" not in p:
        p["retry_count"] = 0
    p["retry_count"] += 1
    return p


def handler_error(p: dict) -> dict:
    """Handle errors."""
    p["error_handled"] = True
    return p


def handler_finalize(p: dict) -> dict:
    """Final processing step."""
    p["finalized"] = True
    return p
