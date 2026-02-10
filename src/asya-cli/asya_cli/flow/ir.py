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
class Return(IROperation):
    pass
