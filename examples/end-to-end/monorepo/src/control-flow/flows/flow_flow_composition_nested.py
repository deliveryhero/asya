"""Nested flow composition: three levels of @flow inlining.

Demonstrates multiple nesting levels producing nested groups in graph.json.
Each reference to the same inner flow creates NEW actor instances.
"""

from _asya_utils import actor, flow


@actor
def tokenize(p: dict) -> dict:
    return p


@actor
def parse_syntax(p: dict) -> dict:
    return p


@actor
def analyze_semantics(p: dict) -> dict:
    return p


@actor
def optimize(p: dict) -> dict:
    return p


@actor
def emit_code(p: dict) -> dict:
    return p


@flow
def frontend(p: dict) -> dict:
    p = tokenize(p)
    p = parse_syntax(p)
    return p


@flow
def middle(p: dict) -> dict:
    p = frontend(p)
    p = analyze_semantics(p)
    return p


@flow
def compiler_pipeline(p: dict) -> dict:
    p = middle(p)
    p = optimize(p)
    p = emit_code(p)
    return p
