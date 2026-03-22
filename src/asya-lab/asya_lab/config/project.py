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
    from asya_lab.flow.rules import CompilerRules

from omegaconf import DictConfig, OmegaConf

from asya_lab.config.store import ConfigStore


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

    def resolve_image(self, handler_name: str) -> str:
        """Resolve a handler name to a container image reference.

        Resolution order:
        1. Specific build entry whose module prefix matches handler_name.
        2. Wildcard build entry (module: "*") — '*' in the image field
           is replaced with the handler's K8s name (hyphens).
        3. KeyError if nothing matches.
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

        if wildcard_entry is not None:
            k8s_name = handler_name.replace("_", "-")
            return str(wildcard_entry["image"]).replace("*", k8s_name)

        raise KeyError(
            f"Cannot resolve image for handler '{handler_name}': "
            f"no matching build entry found. "
            f"Add a build entry or a wildcard (module: '*') to .asya/config.yaml"
        )

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
