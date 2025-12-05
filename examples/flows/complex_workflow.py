"""
Complex workflow example.

Demonstrates nested control structures combining if/else and while loops.
"""

from typing import Dict


def preprocess(p: Dict) -> Dict:
    """Initial preprocessing."""
    p["stage"] = "preprocessed"
    return p


def validate(p: Dict) -> Dict:
    """Validate data."""
    p["valid"] = p.get("data") is not None
    return p


def enrich_data(p: Dict) -> Dict:
    """Enrich data with additional information."""
    p["enriched"] = True
    return p


def transform_batch(p: Dict) -> Dict:
    """Transform batch of items."""
    if "batch_count" not in p:
        p["batch_count"] = 0
    p["batch_count"] += 1
    return p


def check_quality(p: Dict) -> Dict:
    """Check quality metrics."""
    p["quality_checked"] = True
    p["quality_score"] = p.get("batch_count", 0) * 10
    return p


def retry_handler(p: Dict) -> Dict:
    """Handle retry logic."""
    p["retried"] = True
    if "retry_count" not in p:
        p["retry_count"] = 0
    p["retry_count"] += 1
    return p


def error_handler(p: Dict) -> Dict:
    """Handle errors."""
    p["error_handled"] = True
    return p


def finalize(p: Dict) -> Dict:
    """Final processing step."""
    p["finalized"] = True
    return p


def flow_complex_workflow(p: Dict) -> Dict:
    p = preprocess(p)
    p = validate(p)

    if not p["valid"]:
        p = error_handler(p)
        return p

    if p.get("needs_enrichment"):
        p = enrich_data(p)

        while p.get("batch_count", 0) < p.get("max_batches", 3):
            p = transform_batch(p)
            p = check_quality(p)

            if p["quality_score"] < 20:
                continue

            if p["quality_score"] >= 50:
                break
    else:
        if p.get("requires_retry"):
            p = retry_handler(p)

    p = finalize(p)
    return p
