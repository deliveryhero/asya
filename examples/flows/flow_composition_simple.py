"""Simple flow composition: outer flow calls inner flow.

Demonstrates compile-time inlining -- inner flow's body is expanded
into the outer flow. All actors get asya.sh/flow=outer_pipeline.
"""

from _asya_utils import actor, flow


@actor
def preprocess(p: dict) -> dict:
    return p


@actor
def validate(p: dict) -> dict:
    return p


@actor
def enrich(p: dict) -> dict:
    return p


@actor
def store(p: dict) -> dict:
    return p


@flow
def validation_stage(p: dict) -> dict:
    p = validate(p)
    p = enrich(p)
    return p


@flow
def outer_pipeline(p: dict) -> dict:
    p = preprocess(p)
    p = validation_stage(p)
    p = store(p)
    return p
