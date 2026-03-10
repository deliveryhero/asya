# Refactor: Two-Layer Config Architecture

Design doc: `.aint/aints/asya-lab/research-config-setup.md`

## Problem

The current `asya_lab/config/` module mixes syntactic concerns (OmegaConf
loading, merging, resolver registration) with semantic concerns (Asya path
resolution, template context, image resolution). Specific issues:

1. **`AsyaConfig`** is a DictConfig proxy that adds one real method
   (`resolve_path`). Everything else is passthrough. Not worth a class.
2. **`ConfigLoader`** uses a module-global `_active_loader` to bridge instance
   state into OmegaConf's process-global resolver callbacks.
3. **No provenance** -- when config values conflict, there's no way to see which
   `.asya/` directory contributed a given key.
4. **`stamper.py`** mixes template resolution with kustomize directory stamping
   and duplicates config access patterns (`_resolve_config`,
   `_build_template_context`, `_resolve_handler_image`, `_get_contexts`).
5. **Dangling functions** -- `_resolve_relative_paths`, `load_asya_dir`,
   `_resolve_arg` are module-level functions that belong inside classes.

## Design

Two layers with clear responsibilities:

```
+---------------------------------------------------------+
|  Semantic Layer: AsyaProject                            |
|  (asya_lab/config/project.py)                           |
|                                                         |
|  resolve_path()  build_template_context()               |
|  resolve_image() get_contexts()                         |
+---------------------------------------------------------+
|  Syntactic Layer: ConfigStore                           |
|  (asya_lab/config/store.py)                             |
|                                                         |
|  walk-up .asya/ discovery, OmegaConf load/merge/resolve |
|  file provenance tracking, ${env:*} / ${arg:*}          |
+---------------------------------------------------------+
|  Discovery: find_git_root, collect_asya_dirs            |
|  (asya_lab/config/discovery.py) -- unchanged            |
+---------------------------------------------------------+
```

### Layer 1: ConfigStore (syntactic)

Pure OmegaConf machinery. No Asya concepts.

```python
# asya_lab/config/store.py

class ConfigStore:
    """Walk-up config loader with OmegaConf merge and provenance tracking.

    Discovers all .asya/ directories from start_dir up to git root,
    loads config.yaml + config.*.yaml from each, merges them
    (root-first, nearest wins), resolves all interpolations, and
    tracks which file contributed each top-level key.
    """

    _resolvers_registered: bool = False   # class-level, once per process
    _instance: ClassVar[ConfigStore | None] = None  # most recent instance;
    # used by _resolve_arg() callback because OmegaConf resolvers are
    # process-global and cannot capture instance state

    def __init__(
        self,
        start_dir: Path,
        *,
        arg_values: dict[str, str] | None = None,
    ) -> None:
        self._arg_values = dict(arg_values) if arg_values else {}
        self._sources: dict[Path, DictConfig] = {}  # file -> loaded config (pre-merge)
        self._asya_dirs: list[Path] = []             # root-first
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
        ConfigStore._instance = self

        self._asya_dirs = collect_asya_dirs(start_dir)
        if not self._asya_dirs:
            raise FileNotFoundError(
                "No .asya/ directory found. Run 'asya init' to create one."
            )

        per_dir_configs = []
        for asya_dir in self._asya_dirs:
            dir_cfg = self._load_asya_dir(asya_dir)
            per_dir_configs.append(dir_cfg)

        if len(per_dir_configs) == 1:
            self._cfg = per_dir_configs[0]
        else:
            self._cfg = OmegaConf.merge(
                *per_dir_configs, list_merge_mode=ListMergeMode.EXTEND
            )

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
                        f, type(cfg).__name__,
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
        """Resolve ./ prefixed paths to absolute paths. Mutates in-place."""
        # (same logic as current _resolve_relative_paths — unchanged)
        ...

    # -- resolver registration (once per process) ---------------------------

    @classmethod
    def _ensure_resolvers(cls) -> None:
        if cls._resolvers_registered:
            return
        cls._resolvers_registered = True

        OmegaConf.register_new_resolver(
            "env", lambda key: os.environ[key], use_cache=False,
        )
        OmegaConf.register_new_resolver(
            "arg", cls._resolve_arg, use_cache=False,
        )

    @classmethod
    def _resolve_arg(cls, key: str, default: str | None = None) -> str:
        """Resolve ${arg:key} from the most recently constructed ConfigStore."""
        if cls._instance and key in cls._instance._arg_values:
            return cls._instance._arg_values[key]
        if default is not None:
            return str(default)
        raise KeyError(f"Missing --arg {key}")
```

**Provenance tracking**: `self._sources` stores each file's pre-merge
DictConfig. OmegaConf doesn't track provenance natively, so we keep the
pre-merge snapshots. To find which files contributed to a key, iterate
`_sources` and check if the key exists in each snapshot. This is simple
and sufficient — deep per-value provenance would require diffing merged
trees, which is overkill.

**Key changes from current `ConfigLoader`:**
- Constructor takes `start_dir` and does everything — no separate `.load()` call
- `_active_loader` module global replaced by `ConfigStore._instance` class attribute
- `_resolve_relative_paths` and `_load_asya_dir` are methods, not module functions
- `sources` dict tracks provenance per file
- No `AsyaConfig` wrapping — returns plain `DictConfig` via `.cfg`
- No `project_root`, `nearest_asya_dir` properties (not used by callers)

### Layer 2: AsyaProject (semantic)

Asya-specific logic. Wraps `ConfigStore`. Only methods that are actually
called by CLI commands or the templater.

```python
# asya_lab/config/project.py

class AsyaProject:
    """Asya project context: config + path resolution + template access.

    Semantic layer on top of ConfigStore. Only provides methods
    that callers actually need — no speculative API surface.
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

        Note: ConfigStore._resolve_relative_paths already converts ./
        prefixed values to absolute paths at load time. This method
        handles the remaining case: values like ".asya/manifests" that
        don't start with ./ but are still relative to project root.

        Example:
            # config.yaml has: compiler.manifests: ".asya/manifests"
            # nearest .asya/ is at /home/user/project/.asya/
            project.resolve_path("compiler.manifests")
            # -> Path("/home/user/project/.asya/manifests")

        Used by all CLI commands to locate manifest and router directories:
            path = project.resolve_path("compiler.manifests") / flow_name
        """
        node: Any = self._store.cfg
        for part in dotted_key.split("."):
            node = getattr(node, part)
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
        Raises if neither is configured — no implicit image guessing.
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
```

**YAGNI**: No `project_root`, `asya_dir`, `templates_dir` properties,
no `explain()`, no template path accessors — unless callers need them.
`resolve_path()` computes project_root inline. Template paths are passed
to `ManifestTemplater` by `flow_cli.py` which already resolves them
from `find_asya_dir()`.

**`resolve_image()` fails loud**: If neither `build` entries nor
`compiler.image_registry` match, it raises `KeyError` with a clear
message. No implicit `{name}:latest` fallback.

### Stamper -> ManifestTemplater

Rename `compiler/stamper.py` to `compiler/templater.py`. Class becomes
`ManifestTemplater`. Changes:

1. **Constructor** takes `AsyaProject` instead of raw config + 4 template paths.
2. **No wrapper methods** — calls `self.project.resolve_image()`,
   `self.project.build_template_context()`, `self.project.get_contexts()`
   directly. No `_resolve_handler_image`, `_resolve_config`,
   `_build_template_context`, `_get_contexts` indirection.
3. **Template resolution** (`_resolve_template`, `_resolve_template_string`,
   `TemplateContext`) stays — it's template-specific logic.

```python
# asya_lab/compiler/templater.py

class ManifestTemplater:
    def __init__(
        self,
        *,
        flow_name: str,
        flow_function: str,
        routers: list[Router],
        router_code: str,
        project: AsyaProject,
        actor_template_path: Path,
        router_template_path: Path | None = None,
        configmap_template_path: Path | None = None,
        kustomization_template_path: Path | None = None,
    ) -> None:
        ...

    def _collect_actors(self) -> list[ActorInfo]:
        ...
        # Direct call, no wrapper:
        image = self.project.resolve_image(actor_name)
        ...

    def _resolve_template(self, actor: ActorInfo) -> dict:
        ...
        # Direct call, no wrapper:
        context = self.project.build_template_context()
        tc = TemplateContext(...)
        context.update(dataclasses.asdict(tc))
        ...

    def _stamp_overlays(self, overlays_dir: Path) -> list[str]:
        # Direct call, no wrapper:
        contexts = self.project.get_contexts()
        ...
```

### CLI callers

All CLI modules currently do:

```python
config = ConfigLoader().load(start_dir)
path = config.resolve_path("compiler.manifests") / flow_name
```

After refactor:

```python
project = AsyaProject.from_dir(start_dir)
path = project.resolve_path("compiler.manifests") / flow_name
```

One-line change per call site. `flow_name` is always kebab-case (hyphens).
The `config_cli.py` `get` command uses `project.cfg` for `OmegaConf.select()`.

## File changes

| Before | After | Notes |
|---|---|---|
| `config/config.py` | `config/store.py` | Syntactic layer: `ConfigStore` |
| `config/config.py` (AsyaConfig) | `config/project.py` | Semantic layer: `AsyaProject` |
| `config/discovery.py` | `config/discovery.py` | Unchanged |
| `config/__init__.py` | `config/__init__.py` | Export `ConfigStore`, `AsyaProject` |
| `compiler/stamper.py` | `compiler/templater.py` | Rename class, use `project` directly |
| CLI modules (7 files) | CLI modules (7 files) | `ConfigLoader` -> `AsyaProject.from_dir` |
| `flow_cli.py` | `flow_cli.py` | `ManifestStamper` -> `ManifestTemplater` |

## Deleted

- `AsyaConfig` class (replaced by `AsyaProject`)
- `ConfigLoader` class (replaced by `ConfigStore`)
- `_active_loader` / `_set_active_loader` module globals
- `_resolve_arg` module function (now `ConfigStore._resolve_arg` classmethod)
- `load_effective_config` convenience function (replaced by `AsyaProject.from_dir`)
- `load_asya_dir` module function (now `ConfigStore._load_asya_dir`)
- `_resolve_relative_paths` module function (now `ConfigStore._resolve_relative_paths`)

## Migration

1. Create `config/store.py` with `ConfigStore`
2. Create `config/project.py` with `AsyaProject`
3. Rename `compiler/stamper.py` -> `compiler/templater.py`
4. Update all CLI callers (mechanical: `ConfigLoader()` -> `AsyaProject.from_dir()`)
5. Update all tests
6. Delete old `config/config.py`
7. Update `config/__init__.py` exports

Steps 1-3 can be done in parallel. Step 4 depends on 1-3. Step 5-7 are cleanup.
