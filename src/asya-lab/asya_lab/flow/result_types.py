"""Flow compiler result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


#: Allowed values for ActorInfo.role
FlowRole = Literal["start", "end", "router", "actor"]


@dataclass
class ActorInfo:
    """Metadata for a single actor in a compiled flow.

    Naming convention:
      name:    K8s name with hyphens (e.g. "handler-a", "start-my-flow")
      handler: Python function reference (e.g. "handler_a", "routers.start_my_flow")
    """

    name: str
    handler: str
    image: str
    role: str  # see FlowRole type alias
    env: list[dict[str, str]] = field(default_factory=list)
    generated: bool = False
    manifest_path: Path | None = None
    source_file: str | None = None
    source_line: int | None = None


@dataclass
class FlowInfo:
    """Result of compiling a flow."""

    flow_name: str
    flow_function: str
    routers_path: Path
    artifacts_dir: Path
    manifests_dir: Path
    graph: dict
    dot: str
    mermaid: str
    actors: list[ActorInfo]
    warnings: list[str] = field(default_factory=list)
    num_actor_calls: int = 0
    num_inline_mutations: int = 0
