"""Semantic config layer: Asya-specific abstractions on top of ConfigStore.

Wraps ConfigStore with methods that callers actually need:
path resolution, template context, image resolution, contexts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from omegaconf import DictConfig, OmegaConf

from asya_lab.config.store import ConfigStore


if TYPE_CHECKING:
    from asya_lab.compiler.rules import RuleEngine
    from asya_lab.flow.rules import CompilerRules

log = logging.getLogger(__name__)


class AsyaProject:
    """Asya project context: config + path resolution + template access.

    Semantic layer on top of ConfigStore. Only provides methods
    that callers actually need.
    """

    def __init__(self, store: ConfigStore) -> None:
        self._store = store

    @classmethod
    def from_dir(
        cls,
        start_dir: Path,
        *,
        arg_values: dict[str, str] | None = None,
    ) -> AsyaProject:
        """Convenience factory: create ConfigStore and wrap it."""
        return cls(ConfigStore(start_dir, arg_values=arg_values))

    # -- config access ------------------------------------------------------

    @property
    def cfg(self) -> DictConfig:
        """The fully resolved OmegaConf config."""
        return self._store.cfg

    # -- path resolution ----------------------------------------------------

    def resolve_path(self, dotted_key: str) -> Path:
        """Resolve a dotted config key to an absolute filesystem path.

        Walks the DictConfig tree using the dotted key to get the string
        value, then resolves it relative to the project root (parent of
        the nearest .asya/ directory).

        ConfigStore._resolve_relative_paths already converts ./
        prefixed values to absolute paths at load time. This method
        handles the remaining case: values like ".asya/manifests" that
        don't start with ./ but are still relative to project root.

        Example:
            # config.yaml has: compiler.manifests: ".asya/manifests"
            # nearest .asya/ is at /home/user/project/.asya/
            project.resolve_path("compiler.manifests")
            # -> Path("/home/user/project/.asya/manifests")
        """
        node: Any = self._store.cfg
        for part in dotted_key.split("."):
            try:
                node = getattr(node, part)
            except AttributeError:
                raise KeyError(f"Config key '{dotted_key}' not found (missing '{part}')") from None
        project_root = self._store.asya_dirs[-1].parent
        return (project_root / str(node)).resolve()

    # -- template context ---------------------------------------------------

    def build_template_context(self) -> dict[str, str]:
        """Build context dict from config `templates:` section."""
        context: dict[str, str] = {}
        templates_cfg = self._store.cfg.get("templates")
        if templates_cfg:
            for key in templates_cfg:
                context[str(key)] = str(templates_cfg[key])
        return context

    # -- image resolution ---------------------------------------------------

    def resolve_image(
        self,
        handler_name: str,
        handler_fqn: str | None = None,
        handler_source: Path | None = None,
    ) -> str:
        """Resolve a handler name to a container image reference.

        Args:
            handler_name: Short actor name (e.g. "analyze").
            handler_fqn: Fully qualified import path (e.g. "nlp.analyzer.analyze").
            handler_source: Absolute path to handler source file.

        Resolution order:
        1. Skaffold artifacts: match handler source file against artifact
           context dirs (longest prefix). Falls back to importlib if no
           source path provided.
        2. Config build entries (legacy): module prefix match or wildcard.
        3. KeyError if nothing matches.
        """
        image = self._resolve_image_from_skaffold(handler_fqn or handler_name, source_path=handler_source)
        if image:
            return image

        # Fall back to config build entries
        cfg = self._store.cfg
        wildcard_entry = None

        if "build" in cfg:
            for entry in cfg["build"]:
                module = str(entry.get("module", ""))
                if module == "*":
                    wildcard_entry = entry
                    continue
                if module and handler_name.startswith(module.replace(".", "_")):
                    return str(entry["image"])

        if wildcard_entry is not None:
            k8s_name = handler_name.replace("_", "-")
            return str(wildcard_entry["image"]).replace("*", k8s_name)

        raise KeyError(
            f"Cannot resolve image for handler '{handler_name}': "
            f"no skaffold artifact matches. "
            f"Ensure a skaffold.yaml exists with the handler's source "
            f"inside an artifact context directory."
        )

    def _resolve_image_from_skaffold(self, handler_name: str, source_path: Path | None = None) -> str | None:
        """Resolve handler -> image via skaffold.yaml.

        If source_path is provided, matches it against artifact context dirs
        (longest prefix wins). If source_path is None but there is exactly
        one skaffold artifact, uses it as the default.
        """
        artifacts = self._collect_skaffold_artifacts()
        if not artifacts:
            log.debug("[skaffold] no skaffold.yaml artifacts found")
            return None

        if source_path is not None:
            source_path = source_path.resolve()
            best_match: tuple[int, str] | None = None
            for context_dir, image_name in artifacts:
                try:
                    source_path.relative_to(context_dir)
                    prefix_len = len(str(context_dir))
                    if best_match is None or prefix_len > best_match[0]:
                        best_match = (prefix_len, image_name)
                except ValueError:
                    continue

            if best_match:
                log.debug(f"[skaffold] {handler_name} -> {best_match[1]} (via {source_path})")
                return best_match[1]
            log.debug(f"[skaffold] no artifact context matches {source_path}")

        # Fallback: if there is exactly one skaffold artifact, use it
        unique_images = {img for _, img in artifacts}
        if len(unique_images) == 1:
            image = next(iter(unique_images))
            log.debug(f"[skaffold] {handler_name} -> {image} (single artifact fallback)")
            return image

        return None

    def _collect_skaffold_artifacts(self) -> list[tuple[Path, str]]:
        """Find all skaffold.yaml files under project root and collect artifacts."""
        if not self._store.asya_dirs:
            return []
        project_root = self._store.asya_dirs[-1].parent
        skip = {".git", ".asya", ".venv", "node_modules", "__pycache__", "compiled"}
        artifacts: list[tuple[Path, str]] = []

        for skaffold_file in sorted(project_root.rglob("skaffold.yaml")):
            if any(part in skip for part in skaffold_file.relative_to(project_root).parts[:-1]):
                continue
            artifacts.extend(_parse_skaffold_artifacts(skaffold_file))

        return artifacts

    # -- rules --------------------------------------------------------------

    def load_rules(self) -> RuleEngine:
        """Load compiler rules from config.compiler.rules.

        Returns a RuleEngine instance with defaults + user rules.
        """
        from asya_lab.compiler.rules import RuleEngine

        return RuleEngine.from_config(self._load_raw_rules_config())

    def load_context_manager_rules(self) -> CompilerRules:
        """Load context manager rules from config.compiler.rules.

        Filters for entries with ``scope: context-manager`` and returns
        a CompilerRules instance with defaults + user rules.
        """
        from asya_lab.flow.rules import CompilerRules

        return CompilerRules.from_config(self._load_raw_rules_config())

    def _load_raw_rules_config(self) -> list[dict] | None:
        """Load raw compiler rules list from config.compiler.rules."""
        cfg = self._store.cfg
        if "compiler" in cfg and "rules" in cfg["compiler"]:
            raw = OmegaConf.to_container(cfg["compiler"]["rules"], resolve=True)
            if isinstance(raw, list):
                return raw
        return None

    # -- contexts -----------------------------------------------------------

    def get_contexts(self) -> list[str]:
        """Get deployment context names from config."""
        if "contexts" in self._store.cfg:
            return list(self._store.cfg["contexts"].keys())
        return []


# ---------------------------------------------------------------------------
# Skaffold helpers (module-level)
# ---------------------------------------------------------------------------


def _find_skaffold_up(start_dir: Path, stop_dir: Path) -> Path | None:
    """Walk up from start_dir to stop_dir looking for skaffold.yaml."""
    current = start_dir.resolve()
    stop = stop_dir.resolve()
    while True:
        candidate = current / "skaffold.yaml"
        if candidate.is_file():
            return candidate
        if current == stop or current == current.parent:
            return None
        current = current.parent


def _parse_skaffold_artifacts(skaffold_file: Path) -> list[tuple[Path, str]]:
    """Parse a skaffold.yaml and return (context_abs_path, image_name) pairs."""
    import yaml as _yaml

    try:
        config = _yaml.safe_load(skaffold_file.read_text()) or {}
    except Exception:
        return []

    skaffold_dir = skaffold_file.parent
    artifacts: list[tuple[Path, str]] = []
    for artifact in config.get("build", {}).get("artifacts", []):
        image = artifact.get("image", "")
        context = artifact.get("context", ".")
        context_dir = (skaffold_dir / context).resolve()
        artifacts.append((context_dir, image))

    return artifacts
