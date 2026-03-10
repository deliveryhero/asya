"""Config loading with OmegaConf walk-up merge.

Two-layer architecture:
1. OmegaConf (syntactic): YAML loading, interpolation, merge with ListMergeMode.EXTEND.
2. Asya (semantic): walk-up file discovery, filename-to-key convention,
   directory-to-key convention, schema validation.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from omegaconf import DictConfig, ListMergeMode, OmegaConf

from asya_lab.config.discovery import collect_asya_dirs


log = logging.getLogger(__name__)

_RELATIVE_PATH_PATTERN = re.compile(r"^\./")


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

    def load(self, start_dir: Path) -> DictConfig:
        """Walk up from start_dir, collect and merge all .asya/ configs.

        Merges root-first (outermost config is base, most local overrides).
        Uses OmegaConf with ListMergeMode.EXTEND for list concatenation.
        """
        _set_active_loader(self)

        asya_dirs = collect_asya_dirs(start_dir)
        if not asya_dirs:
            raise FileNotFoundError("No .asya/ directory found. Run 'asya init' to create one.")

        configs = [load_asya_dir(d) for d in asya_dirs]

        if len(configs) == 1:
            return configs[0]

        return OmegaConf.merge(*configs, list_merge_mode=ListMergeMode.EXTEND)


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
    raise KeyError(f"${{dynamic:{key}}} is only available during compilation")


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
        if subdir.name in ("manifests", "compose"):
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


def load_effective_config(
    start_dir: Path,
    *,
    arg_values: dict[str, str] | None = None,
) -> DictConfig:
    """Convenience wrapper: create a ConfigLoader and load config.

    Prefer using ConfigLoader directly for repeated operations or
    when you need to set dynamic values (e.g. during compilation).
    """
    loader = ConfigLoader(arg_values=arg_values)
    return loader.load(start_dir)
