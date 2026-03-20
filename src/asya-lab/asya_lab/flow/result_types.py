"""Flow compiler result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
    flow_role: str  # "entry" | "exit" | "entryexit" | "router" | "actor"
    env: list[dict[str, str]] = field(default_factory=list)
    is_generated: bool = False
    manifest_path: Path | None = None
    source_file: str | None = None
    source_line: int | None = None


@dataclass
class FlowInfo:
    """Result of compiling a flow."""

    flow_name: str
    flow_function: str
    routers_path: Path
    manifests_dir: Path
    graph: dict
    dot: str
    mermaid: str
    svg: str | None
    actors: list[ActorInfo]
    warnings: list[str] = field(default_factory=list)
