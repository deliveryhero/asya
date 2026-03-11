"""Semantic config layer: Asya-specific abstractions on top of ConfigStore.

Wraps ConfigStore with methods that callers actually need:
path resolution, template context, image resolution, contexts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from asya_lab.compiler.rules import RuleEngine

from omegaconf import DictConfig, OmegaConf

from asya_lab.config.store import ConfigStore


log = logging.getLogger(__name__)


class ImageNotConfiguredError(Exception):
    """Raised when no Docker image is configured for a handler actor."""

    def __init__(self, handler_name: str, k8s_name: str) -> None:
        self.handler_name = handler_name
        self.k8s_name = k8s_name
        super().__init__(
            f"No Docker image configured for handler '{handler_name}'.\n"
            f"Add a build entry to .asya/config.yaml:\n"
            f"\n"
            f"  build:\n"
            f"    - module: {handler_name}\n"
            f"      image: <your-image>:<tag>\n"
        )


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

    def resolve_image(self, handler_name: str) -> str:
        """Resolve a handler name to a container image reference.

        Checks build entries for a module prefix match.
        Raises ImageNotConfiguredError if no matching entry is found.
        """
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

        k8s_name = handler_name.replace("_", "-")
        raise ImageNotConfiguredError(
            handler_name=handler_name,
            k8s_name=k8s_name,
        )

    # -- rules --------------------------------------------------------------

    def load_rules(self) -> RuleEngine:
        """Load compiler rules from config.compiler.rules.

        Returns a RuleEngine instance with defaults + user rules.
        """
        from asya_lab.compiler.rules import RuleEngine

        cfg = self._store.cfg
        rules_cfg = None
        if "compiler" in cfg and "rules" in cfg["compiler"]:
            raw = OmegaConf.to_container(cfg["compiler"]["rules"], resolve=True)
            if isinstance(raw, list):
                rules_cfg = raw
        return RuleEngine.from_config(rules_cfg)

    # -- contexts -----------------------------------------------------------

    def get_contexts(self) -> list[str]:
        """Get deployment context names from config."""
        if "contexts" in self._store.cfg:
            return list(self._store.cfg["contexts"].keys())
        return []
