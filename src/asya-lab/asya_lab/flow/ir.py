"""Intermediate representation for flow operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IROperation:
    lineno: int


@dataclass
class ActorCall(IROperation):
    name: str


@dataclass
class Mutation(IROperation):
    code: str


@dataclass
class Condition(IROperation):
    test: str
    true_branch: list[IROperation]
    false_branch: list[IROperation]


@dataclass
class Convergence(IROperation):
    label: str


@dataclass
class WhileLoop(IROperation):
    test: str | None  # None means `while True`
    body: list[IROperation]


@dataclass
class Break(IROperation):
    pass


@dataclass
class Continue(IROperation):
    pass


@dataclass
class ExceptHandler(IROperation):
    error_types: list[str] | None  # None = bare except (catch-all)
    body: list[IROperation]


@dataclass
class TryExcept(IROperation):
    body: list[IROperation]
    handlers: list[ExceptHandler]
    finally_body: list[IROperation]


@dataclass
class Raise(IROperation):
    pass


@dataclass
class FanOutCall(IROperation):
    target_key: str  # JSON Pointer, e.g. "/results"
    pattern: str  # "comprehension" | "literal" | "gather"
    actor_calls: list[tuple[str, str]]  # (actor_name, payload_expr) pairs
    iter_var: str | None = None  # Loop variable for comprehension/gather-generator
    iterable: str | None = None  # Iterable expression for comprehension/gather-generator


@dataclass
class Return(IROperation):
    pass
