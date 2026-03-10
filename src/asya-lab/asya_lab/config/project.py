"""Semantic config layer: Asya-specific abstractions on top of ConfigStore.

Wraps ConfigStore with methods that callers actually need:
path resolution, template context, image resolution, contexts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from omegaconf import DictConfig

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

        Checks build entries first (module prefix match).
        Falls back to compiler.image_registry + handler name.
        Raises KeyError if neither is configured.
        """
        cfg = self._store.cfg

        # Check build entries (module prefix match)
        if "build" in cfg:
            for entry in cfg["build"]:
                module = str(entry.get("module", ""))
                if module and handler_name.startswith(module.replace(".", "_")):
                    return str(entry["image"])

        # Fall back to image_registry
        if "compiler" in cfg and "image_registry" in cfg["compiler"]:
            registry = str(cfg["compiler"]["image_registry"])
            k8s_name = handler_name.replace("_", "-")
            return f"{registry}/{k8s_name}:latest"

        raise KeyError(
            f"Cannot resolve image for handler '{handler_name}': "
            f"no matching build entry and no compiler.image_registry configured. "
            f"Add a build entry or set compiler.image_registry in .asya/config.yaml"
        )

    # -- contexts -----------------------------------------------------------

    def get_contexts(self) -> list[str]:
        """Get deployment context names from config."""
        if "contexts" in self._store.cfg:
            return list(self._store.cfg["contexts"].keys())
        return []
