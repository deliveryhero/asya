"""Syntactic config layer: OmegaConf walk-up merge with provenance tracking.

Pure OmegaConf machinery. No Asya-specific concepts.

Discovers all .asya/ directories from start_dir up to git root,
loads config.yaml + config.*.yaml from each, merges them
(root-first, nearest wins), resolves all interpolations, and
tracks which file contributed each top-level key.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import ClassVar

from omegaconf import DictConfig, ListMergeMode, OmegaConf

from asya_lab.config.discovery import collect_asya_dirs


log = logging.getLogger(__name__)

_RELATIVE_PATH_PATTERN = re.compile(r"^\./")


class ConfigStore:
    """Walk-up config loader with OmegaConf merge and provenance tracking.

    Discovers all .asya/ directories from start_dir up to git root,
    loads config.yaml + config.*.yaml from each, merges them
    (root-first, nearest wins), resolves all interpolations, and
    tracks which file contributed each top-level key.
    """

    _resolvers_registered: bool = False

    # Most recent instance; used by _resolve_arg() callback because
    # OmegaConf resolvers are process-global and cannot capture instance state.
    _instance: ClassVar[ConfigStore | None] = None

    def __init__(
        self,
        start_dir: Path,
        *,
        arg_values: dict[str, str] | None = None,
    ) -> None:
        self._arg_values = dict(arg_values) if arg_values else {}
        self._sources: dict[Path, DictConfig] = {}  # file -> loaded config (pre-merge)
        self._asya_dirs: list[Path] = []  # root-first
        self._cfg: DictConfig | None = None

        self._ensure_resolvers()
        self._load(start_dir)

    # -- public API ---------------------------------------------------------

    @property
    def cfg(self) -> DictConfig:
        """Fully merged and resolved config."""
        assert self._cfg is not None
        return self._cfg

    @property
    def asya_dirs(self) -> list[Path]:
        """All discovered .asya/ dirs, root-first."""
        return list(self._asya_dirs)

    @property
    def sources(self) -> dict[Path, DictConfig]:
        """Map of file path -> its loaded (pre-merge) OmegaConf object.

        For provenance: which file contributed what.
        """
        return dict(self._sources)

    # -- internals ----------------------------------------------------------

    def _load(self, start_dir: Path) -> None:
        """Walk up, collect .asya/ dirs, load and merge all config files."""
        # TODO: last-one-wins singleton — fragile if multiple ConfigStores
        # are created in the same process (e.g. tests). OmegaConf resolvers
        # are process-global so there's no clean way to scope them to an
        # instance. Callers should avoid creating redundant instances.
        ConfigStore._instance = self

        self._asya_dirs = collect_asya_dirs(start_dir)
        if not self._asya_dirs:
            raise FileNotFoundError("No .asya/ directory found. Run 'asya init' to create one.")

        per_dir_configs = []
        for asya_dir in self._asya_dirs:
            dir_cfg = self._load_asya_dir(asya_dir)
            per_dir_configs.append(dir_cfg)

        if len(per_dir_configs) == 1:
            self._cfg = per_dir_configs[0]
        else:
            self._cfg = OmegaConf.merge(*per_dir_configs, list_merge_mode=ListMergeMode.EXTEND)

    def _load_asya_dir(self, asya_dir: Path) -> DictConfig:
        """Load all config files from a single .asya/ directory.

        Applies filename-to-key convention with dotted section nesting.
        Populates self._sources with file -> pre-merge DictConfig entries.
        """
        result = OmegaConf.create({})

        config_files = sorted(asya_dir.glob("config*.yaml"))
        for f in config_files:
            cfg = OmegaConf.load(f)
            if f.name == "config.yaml":
                if not isinstance(cfg, DictConfig):
                    log.warning(
                        "Skipping %s: root is %s, expected mapping",
                        f,
                        type(cfg).__name__,
                    )
                    continue
                self._resolve_relative_paths(cfg, base_dir=asya_dir.parent)
                self._sources[f] = cfg
                result = OmegaConf.merge(result, cfg)
            else:
                if isinstance(cfg, DictConfig):
                    self._resolve_relative_paths(cfg, base_dir=asya_dir.parent)
                section = f.name.removeprefix("config.").removesuffix(".yaml")
                parts = section.split(".")
                # Build nested structure for dotted sections
                current = result
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = OmegaConf.create({})
                    current = current[part]
                leaf_key = parts[-1]
                if leaf_key in current:
                    existing = OmegaConf.create({leaf_key: current[leaf_key]})
                    new = OmegaConf.create({leaf_key: cfg})
                    merged = OmegaConf.merge(existing, new)
                    current[leaf_key] = merged[leaf_key]
                else:
                    current[leaf_key] = cfg
                # Track provenance with the effective key path
                self._sources[f] = OmegaConf.create({section: cfg})

        return result

    @staticmethod
    def _resolve_relative_paths(cfg: DictConfig, base_dir: Path) -> None:
        """Resolve ./ prefixed paths to absolute paths relative to base_dir.

        Mutates the config in-place. Only processes string values that start
        with './'. Skips values containing ${...} interpolations.

        Uses OmegaConf.to_container(resolve=False) to get raw values without
        triggering interpolation, then OmegaConf.update() to write back.
        """
        raw = OmegaConf.to_container(cfg, resolve=False)
        ConfigStore._walk_and_resolve(cfg, raw, base_dir, prefix="")

    @staticmethod
    def _walk_and_resolve(cfg: DictConfig, raw: dict | list, base_dir: Path, prefix: str) -> None:
        """Walk raw container and resolve ./ paths back into cfg."""
        if isinstance(raw, dict):
            for key, value in raw.items():
                dotted = f"{prefix}.{key}" if prefix else str(key)
                if isinstance(value, dict):
                    sub = OmegaConf.select(cfg, dotted)
                    if OmegaConf.is_dict(sub):
                        ConfigStore._walk_and_resolve(cfg, value, base_dir, dotted)
                elif isinstance(value, list):
                    ConfigStore._walk_and_resolve(cfg, value, base_dir, dotted)
                elif isinstance(value, str):
                    if _RELATIVE_PATH_PATTERN.match(value) and "${" not in value:
                        resolved = str((base_dir / value).resolve())
                        OmegaConf.update(cfg, dotted, resolved)
        elif isinstance(raw, list):
            for i, item in enumerate(raw):
                dotted = f"{prefix}.{i}" if prefix else str(i)
                if isinstance(item, dict):
                    sub = OmegaConf.select(cfg, dotted)
                    if OmegaConf.is_dict(sub):
                        ConfigStore._walk_and_resolve(cfg, item, base_dir, dotted)
                elif isinstance(item, str):
                    if _RELATIVE_PATH_PATTERN.match(item) and "${" not in item:
                        resolved = str((base_dir / item).resolve())
                        OmegaConf.update(cfg, dotted, resolved)

    # -- resolver registration (once per process) ---------------------------

    @classmethod
    def _ensure_resolvers(cls) -> None:
        if cls._resolvers_registered:
            return
        cls._resolvers_registered = True

        OmegaConf.register_new_resolver(
            "env",
            lambda key: os.environ[key],
            use_cache=False,
        )
        OmegaConf.register_new_resolver(
            "arg",
            cls._resolve_arg,
            use_cache=False,
        )

    @classmethod
    def _resolve_arg(cls, key: str, default: str | None = None) -> str:
        """Resolve ${arg:key} from the most recently constructed ConfigStore."""
        if cls._instance and key in cls._instance._arg_values:
            return cls._instance._arg_values[key]
        if default is not None:
            return str(default)
        raise KeyError(f"Missing --arg {key}")
