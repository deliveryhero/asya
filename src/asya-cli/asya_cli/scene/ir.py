"""Intermediate representation for scene operations."""

from dataclasses import dataclass
from typing import List


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
    true_branch: List[IROperation]
    false_branch: List[IROperation]


@dataclass
class Convergence(IROperation):
    label: str
