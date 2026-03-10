"""Config loading with OmegaConf walk-up merge.

Two-layer architecture:
1. OmegaConf (syntactic): YAML loading, interpolation, merge with ListMergeMode.EXTEND.
2. Asya (semantic): walk-up file discovery, filename-to-key convention, schema validation.

Config is fully resolved at load time using env and arg resolvers.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, ListMergeMode, OmegaConf

from asya_lab.config.discovery import collect_asya_dirs


log = logging.getLogger(__name__)

_RELATIVE_PATH_PATTERN = re.compile(r"^\./")


# ---------------------------------------------------------------------------
# FlowContext — typed bundle of dynamic values for path resolution
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FlowContext:
    """Typed bundle of dynamic values derived from a flow.

    Ensures both naming variants are always provided together.
    Use factory methods instead of the constructor directly.
    """

    flow_function: str  # Python name: underscores (e.g. "order_processing")
    flow_name: str  # K8s name: hyphens (e.g. "order-processing")

    @classmethod
    def from_flow_name(cls, flow_name: str) -> FlowContext:
        """Create from a kebab-case K8s name (e.g. "order-processing")."""
        flow_function = flow_name.replace("-", "_")
        return cls(flow_function=flow_function, flow_name=flow_name)

    @classmethod
    def from_flow_function(cls, flow_function: str) -> FlowContext:
        """Create from a Python function name (e.g. "order_processing")."""
        flow_name = flow_function.replace("_", "-")
        return cls(flow_function=flow_function, flow_name=flow_name)

    @classmethod
    def placeholder(cls) -> FlowContext:
        """Dummy context for resolving the manifests root directory.

        The resolved path's leaf is stripped via .parent, so the value
        doesn't matter — it just needs to be non-empty.
        """
        return cls(flow_function="_", flow_name="_")


# ---------------------------------------------------------------------------
# AsyaConfig — config wrapper
# ---------------------------------------------------------------------------


class AsyaConfig:
    """Config wrapper around OmegaConf DictConfig.

    Provides path resolution and project metadata alongside the raw config.

    Note: ``__getattr__`` proxies to the underlying DictConfig, but only
    as a fallback — Python calls ``__getattr__`` only when normal attribute
    lookup (``self.__dict__``, class descriptors) fails.  So private attrs
    like ``self._cfg`` set in ``__init__`` are found normally.
    """

    def __init__(self, cfg: DictConfig, asya_dir: Path) -> None:
        self._cfg = cfg
        self._asya_dir = asya_dir

    # -- identity / location ------------------------------------------------

    @property
    def asya_dir(self) -> Path:
        """The .asya/ directory this config was loaded from."""
        return self._asya_dir

    @property
    def project_root(self) -> Path:
        """Parent of .asya/ — the project root directory."""
        return self._asya_dir.parent

    @property
    def raw(self) -> DictConfig:
        """The underlying OmegaConf DictConfig (for OmegaConf.to_container etc)."""
        return self._cfg

    # -- path resolution ----------------------------------------------------

    def resolve_path(self, dotted_key: str) -> Path:
        """Resolve a dotted config key to an absolute path.

        The raw config value is treated as a path relative to *project_root*.
        """
        node: Any = self._cfg
        for part in dotted_key.split("."):
            node = getattr(node, part)
        return (self.project_root / str(node)).resolve()

    # -- DictConfig proxy ---------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._cfg.get(key, default)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cfg, name)

    def __contains__(self, key: object) -> bool:
        return key in self._cfg

    def __iter__(self):
        return iter(self._cfg)

    def __getitem__(self, key: str) -> Any:
        return self._cfg[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._cfg[key] = value


# ---------------------------------------------------------------------------
# ConfigLoader
# ---------------------------------------------------------------------------


class ConfigLoader:
    """Loads and merges .asya/ config files with OmegaConf.

    Encapsulates resolver state (arg values) so callers
    don't rely on module-level mutable globals. OmegaConf resolvers
    are process-global, so they delegate to the most recently created
    loader instance.
    """

    _resolvers_registered: bool = False

    def __init__(
        self,
        *,
        arg_values: dict[str, str] | None = None,
    ) -> None:
        self.arg_values: dict[str, str] = dict(arg_values) if arg_values else {}
        self._ensure_resolvers()

    @classmethod
    def _ensure_resolvers(cls) -> None:
        """Register OmegaConf resolvers once per process."""
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
            _resolve_arg,
            use_cache=False,
        )

    def load(self, start_dir: Path) -> AsyaConfig:
        """Walk up from start_dir, collect and merge all .asya/ configs.

        Returns a fully resolved AsyaConfig.
        """
        _set_active_loader(self)

        asya_dirs = collect_asya_dirs(start_dir)
        if not asya_dirs:
            raise FileNotFoundError("No .asya/ directory found. Run 'asya init' to create one.")

        configs = [load_asya_dir(d) for d in asya_dirs]

        if len(configs) == 1:
            cfg = configs[0]
        else:
            cfg = OmegaConf.merge(*configs, list_merge_mode=ListMergeMode.EXTEND)

        # Nearest (most local) .asya/ dir is last in the list
        return AsyaConfig(cfg, asya_dirs[-1])


# ---------------------------------------------------------------------------
# Module-level resolver state
# ---------------------------------------------------------------------------


_active_loader: ConfigLoader | None = None


def _set_active_loader(loader: ConfigLoader) -> None:
    global _active_loader
    _active_loader = loader


def _resolve_arg(key: str, default: str | None = None) -> str:
    """Resolve ${arg:key} or ${arg:key,default} from active loader."""
    if _active_loader and key in _active_loader.arg_values:
        return _active_loader.arg_values[key]
    if default is not None:
        return str(default)
    raise KeyError(f"Missing --arg {key}")


# ---------------------------------------------------------------------------
# Config file loading
# ---------------------------------------------------------------------------


def _resolve_relative_paths(cfg: DictConfig, base_dir: Path) -> None:
    """Resolve ./ prefixed paths to absolute paths relative to base_dir.

    Mutates the config in-place. Only processes string values that start
    with './'. Skips values containing ${...} interpolations.
    """
    for key in cfg:
        if OmegaConf.is_missing(cfg, key):
            continue
        val = cfg._get_node(key)
        if val is None:
            continue
        if OmegaConf.is_dict(val):
            _resolve_relative_paths(val, base_dir)
        elif OmegaConf.is_list(val):
            for i in range(len(val)):
                item = val._get_node(i)
                if OmegaConf.is_dict(item):
                    _resolve_relative_paths(item, base_dir)
                elif hasattr(item, "_value") and isinstance(item._value(), str):
                    raw = item._value()
                    if _RELATIVE_PATH_PATTERN.match(raw) and "${" not in raw:
                        resolved = str((base_dir / raw).resolve())
                        OmegaConf.update(val, i, resolved)
        elif hasattr(val, "_value"):
            raw = val._value()
            if isinstance(raw, str) and _RELATIVE_PATH_PATTERN.match(raw) and "${" not in raw:
                resolved = str((base_dir / raw).resolve())
                OmegaConf.update(cfg, key, resolved)


def load_asya_dir(asya_dir: Path) -> DictConfig:
    """Load all config files from a single .asya/ directory.

    Applies filename-to-key convention: config.yaml is root,
    config.<section>.yaml merges under <section>: key.
    Dotted sections create nested dicts (e.g. config.compiler.rules.yaml).
    """
    result = OmegaConf.create({})

    # Load config*.yaml files (filename-to-key convention with dotted nesting)
    config_files = sorted(asya_dir.glob("config*.yaml"))
    for f in config_files:
        cfg = OmegaConf.load(f)
        if f.name == "config.yaml":
            if not isinstance(cfg, DictConfig):
                log.warning("Skipping %s: root is %s, expected mapping", f, type(cfg).__name__)
                continue
            _resolve_relative_paths(cfg, base_dir=asya_dir.parent)
            result = OmegaConf.merge(result, cfg)
        else:
            if isinstance(cfg, DictConfig):
                _resolve_relative_paths(cfg, base_dir=asya_dir.parent)
            section = f.name.removeprefix("config.").removesuffix(".yaml")
            parts = section.split(".")
            # Build nested structure
            current = result
            for part in parts[:-1]:
                if part not in current:
                    current[part] = OmegaConf.create({})
                current = current[part]
            # Merge at the leaf
            leaf_key = parts[-1]
            if leaf_key in current:
                existing = OmegaConf.create({leaf_key: current[leaf_key]})
                new = OmegaConf.create({leaf_key: cfg})
                merged = OmegaConf.merge(existing, new)
                current[leaf_key] = merged[leaf_key]
            else:
                current[leaf_key] = cfg

    return result


def load_effective_config(
    start_dir: Path,
    *,
    arg_values: dict[str, str] | None = None,
) -> AsyaConfig:
    """Convenience wrapper: create a ConfigLoader and load config.

    Prefer using ConfigLoader directly for repeated operations.
    """
    loader = ConfigLoader(arg_values=arg_values)
    return loader.load(start_dir)
