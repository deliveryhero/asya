"""Config loading with OmegaConf walk-up merge.

Two-layer architecture:
1. OmegaConf (syntactic): YAML loading, interpolation, merge with ListMergeMode.EXTEND.
2. Asya (semantic): walk-up file discovery, filename-to-key convention,
   directory-to-key convention, schema validation.

Config objects support two-phase initialization:
  Phase 1 (load):         var/env/arg resolvers work; dynamic fields deferred.
  Phase 2 (with_values):  caller supplies remaining values; all fields resolve.

Accessing a field with unresolved interpolations raises ConfigNotFinalizedError.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
from pathlib import Path
from typing import Any, NoReturn

from omegaconf import DictConfig, ListMergeMode, OmegaConf

from asya_lab.config.discovery import MANIFESTS_DIR, collect_asya_dirs


log = logging.getLogger(__name__)

_RELATIVE_PATH_PATTERN = re.compile(r"^\./")


# ---------------------------------------------------------------------------
# FlowContext — typed bundle of dynamic values for path resolution
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class FlowContext:
    """Typed bundle of dynamic values derived from a flow.

    Ensures all three naming variants are always provided together.
    Use factory methods instead of the constructor directly.
    """

    flow_function: str  # Python name: underscores (e.g. "order_processing")
    flow_name: str  # K8s name: hyphens (e.g. "order-processing")
    flow: str  # Alias for flow_name (for ${dynamic:flow} in templates)

    @classmethod
    def from_flow_name(cls, flow_name: str) -> FlowContext:
        """Create from a kebab-case K8s name (e.g. "order-processing")."""
        flow_function = flow_name.replace("-", "_")
        return cls(flow_function=flow_function, flow_name=flow_name, flow=flow_name)

    @classmethod
    def from_flow_function(cls, flow_function: str) -> FlowContext:
        """Create from a Python function name (e.g. "order_processing")."""
        flow_name = flow_function.replace("_", "-")
        return cls(flow_function=flow_function, flow_name=flow_name, flow=flow_name)

    @classmethod
    def placeholder(cls) -> FlowContext:
        """Dummy context for resolving the manifests root directory.

        The resolved path's leaf is stripped via .parent, so the value
        doesn't matter — it just needs to be non-empty.
        """
        return cls(flow_function="_", flow_name="_", flow="_")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigNotFinalizedError(Exception):
    """Raised when accessing a config value with unresolved interpolations."""


# ---------------------------------------------------------------------------
# AsyaConfig — two-phase config wrapper
# ---------------------------------------------------------------------------


class AsyaConfig:
    """Two-phase config wrapper around OmegaConf DictConfig.

    Purely syntactic — does not know the meaning of specific resolver types.
    Tracks whether interpolations are resolved and gives helpful errors
    listing which fields remain unresolved.

    Note: ``__getattr__`` proxies to the underlying DictConfig, but only
    as a fallback — Python calls ``__getattr__`` only when normal attribute
    lookup (``self.__dict__``, class descriptors) fails.  So private attrs
    like ``self._cfg`` set in ``__init__`` are found normally.
    """

    def __init__(self, cfg: DictConfig, loader: ConfigLoader, asya_dir: Path) -> None:
        self._cfg = cfg
        self._loader = loader
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

    # -- two-phase initialization -------------------------------------------

    def with_values(self, ctx: FlowContext | None = None, **extras: str) -> AsyaConfig:
        """Supply values for unresolved interpolations.

        Accepts a FlowContext for the standard flow triple, plus optional
        **extras for template-specific values (actor_name, handler, etc.).
        Returns self for chaining.
        """
        if ctx is not None:
            self._loader.dynamic_values.update(dataclasses.asdict(ctx))
        self._loader.dynamic_values.update(extras)
        _set_active_loader(self._loader)
        return self

    # -- path resolution ----------------------------------------------------

    def resolve_path(self, dotted_key: str) -> Path:
        """Resolve a dotted config key to an absolute path.

        The raw config value is treated as a path relative to *project_root*.
        Raises ConfigNotFinalizedError if the value has unresolved interpolations.
        """
        self._activate()
        try:
            node: Any = self._cfg
            for part in dotted_key.split("."):
                node = getattr(node, part)
            return (self.project_root / str(node)).resolve()
        except Exception as e:
            self._raise_if_unresolved(dotted_key, e)

    # -- introspection ------------------------------------------------------

    def unresolved(self) -> dict[str, str]:
        """Scan config and return unresolved fields.

        Returns ``{dotted.path: raw_interpolation_or_error}`` for every
        field whose value cannot be resolved with the current set of values.
        """
        self._activate()
        result: dict[str, str] = {}
        _collect_unresolved(self._cfg, "", result)
        return result

    # -- DictConfig proxy ---------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        self._activate()
        try:
            return self._cfg.get(key, default)
        except Exception as e:
            self._raise_if_unresolved(key, e)

    def __getattr__(self, name: str) -> Any:
        self._activate()
        try:
            return getattr(self._cfg, name)
        except AttributeError:
            raise
        except Exception as e:
            self._raise_if_unresolved(name, e)

    def __contains__(self, key: object) -> bool:
        return key in self._cfg

    def __iter__(self):
        return iter(self._cfg)

    def __getitem__(self, key: str) -> Any:
        self._activate()
        try:
            return self._cfg[key]
        except Exception as e:
            self._raise_if_unresolved(key, e)

    def __setitem__(self, key: str, value: Any) -> None:
        self._cfg[key] = value

    # -- internals ----------------------------------------------------------

    def _activate(self) -> None:
        """Ensure this config's loader is the active resolver provider."""
        _set_active_loader(self._loader)

    def _raise_if_unresolved(self, key: str, cause: Exception) -> NoReturn:
        """Re-raise as ConfigNotFinalizedError if unresolved fields exist."""
        pending = self.unresolved()
        if pending:
            fields = "\n".join(f"  {k}: {v}" for k, v in pending.items())
            raise ConfigNotFinalizedError(
                f"Cannot resolve '{key}': config has unresolved interpolations.\n"
                f"Unresolved fields:\n{fields}\n"
                f"Provide values via config.with_values(...)"
            ) from cause
        raise cause


# ---------------------------------------------------------------------------
# ConfigLoader
# ---------------------------------------------------------------------------


class ConfigLoader:
    """Loads and merges .asya/ config files with OmegaConf.

    Encapsulates resolver state (arg and dynamic values) so callers
    don't rely on module-level mutable globals. OmegaConf resolvers
    are process-global, so they delegate to the most recently created
    loader instance.
    """

    _resolvers_registered: bool = False

    def __init__(
        self,
        *,
        arg_values: dict[str, str] | None = None,
        dynamic_values: dict[str, str] | None = None,
    ) -> None:
        self.arg_values: dict[str, str] = dict(arg_values) if arg_values else {}
        self.dynamic_values: dict[str, str] = dict(dynamic_values) if dynamic_values else {}
        _set_active_loader(self)
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
        OmegaConf.register_new_resolver(
            "dynamic",
            _resolve_dynamic,
            use_cache=False,
        )

    def load(self, start_dir: Path) -> AsyaConfig:
        """Walk up from start_dir, collect and merge all .asya/ configs.

        Returns an AsyaConfig that may have unresolved interpolations.
        Call ``.with_values(...)`` to supply missing values before accessing
        fields that depend on them.
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
        return AsyaConfig(cfg, self, asya_dirs[-1])


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


def _resolve_dynamic(key: str) -> str:
    """Resolve ${dynamic:key} from active loader."""
    if _active_loader and key in _active_loader.dynamic_values:
        return _active_loader.dynamic_values[key]
    raise KeyError(f"${{{key}}} not provided — call config.with_values({key}=...)")


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

    Applies directory-to-key convention: subdirectories that contain
    .yaml files are merged under the directory name key.
    """
    result = OmegaConf.create({})

    # 1. Load config*.yaml files (filename-to-key convention)
    config_files = sorted(asya_dir.glob("config*.yaml"))
    for f in config_files:
        cfg = OmegaConf.load(f)
        if not isinstance(cfg, DictConfig):
            log.warning("Skipping %s: root is %s, expected mapping", f, type(cfg).__name__)
            continue
        _resolve_relative_paths(cfg, base_dir=asya_dir.parent)
        if f.name == "config.yaml":
            result = OmegaConf.merge(result, cfg)
        else:
            section = f.name.removeprefix("config.").removesuffix(".yaml")
            if section in result:
                existing = OmegaConf.create({section: result[section]})
                new = OmegaConf.create({section: cfg})
                merged = OmegaConf.merge(existing, new)
                result[section] = merged[section]
            else:
                result[section] = cfg

    # 2. Load directories (directory-to-key convention)
    for subdir in sorted(asya_dir.iterdir()):
        if not subdir.is_dir():
            continue
        if subdir.name in (MANIFESTS_DIR, "compose"):
            continue
        dir_cfg = _load_directory_recursive(subdir)
        if dir_cfg:
            if subdir.name in result:
                existing = OmegaConf.create({subdir.name: result[subdir.name]})
                new = OmegaConf.create({subdir.name: dir_cfg})
                merged = OmegaConf.merge(existing, new)
                result[subdir.name] = merged[subdir.name]
            else:
                result[subdir.name] = dir_cfg

    return result


def _load_directory_recursive(directory: Path) -> DictConfig | None:
    """Recursively load YAML files from a directory into a nested config.

    Files become keys (stem), subdirectories create nested dicts.
    """
    result = OmegaConf.create({})
    has_content = False

    for item in sorted(directory.iterdir()):
        if item.is_file() and item.suffix in (".yaml", ".yml"):
            cfg = OmegaConf.load(item)
            if cfg is not None:
                result[item.stem] = cfg
                has_content = True
        elif item.is_dir():
            sub = _load_directory_recursive(item)
            if sub is not None:
                result[item.name] = sub
                has_content = True

    return result if has_content else None


def _collect_unresolved(cfg: DictConfig, prefix: str, result: dict[str, str]) -> None:
    """Walk config tree and collect fields with unresolved interpolations."""
    for key in cfg:
        path = f"{prefix}.{key}" if prefix else str(key)
        try:
            node = cfg._get_node(key)
        except Exception:
            result[path] = "<inaccessible>"
            continue
        if node is None:
            continue
        if OmegaConf.is_dict(node):
            _collect_unresolved(node, path, result)
        else:
            try:
                _ = cfg[key]  # trigger resolution
            except Exception as e:
                result[path] = str(e)


def load_effective_config(
    start_dir: Path,
    *,
    arg_values: dict[str, str] | None = None,
) -> AsyaConfig:
    """Convenience wrapper: create a ConfigLoader and load config.

    Prefer using ConfigLoader directly for repeated operations or
    when you need to set dynamic values (e.g. during compilation).
    """
    loader = ConfigLoader(arg_values=arg_values)
    return loader.load(start_dir)
