# Research: Compiler Resolution and Build Context Mapping

**Date**: 2026-03-07
**Status**: Informational
**Context**: How the Asya compiler resolves Python handler references to
images, and how `.asya/config.yaml` maps Python packages to OCI images and
build commands.

**Related docs**:
- `research-no-dockerfile.md` -- WHAT builds the image (apko, buildpacks,
  Dockerfile)
- `research-seamless-build.md` -- WHERE/HOW images are built, promotion
  strategies
- `adr.no-cog.md` -- decision to not use Cog

---

## 1. Core Insight: Build Context Follows Python Packages, Not Actors

Build configuration is **per-Python-package**, not per-actor. Multiple actors
can share the same image if their handlers come from the same package.

```
Python package → image entry → OCI image
       ↓
  Multiple actors reference the same image
  (same image, different ASYA_HANDLER env var)
```

Example: `validate_order`, `express_handler`, and `payment_processor` all live
in `e_commerce` package → one image `ghcr.io/org/e-commerce:v1` → three
AsyncActor CRDs, each with different `spec.handler`.

---

## 2. The `.asya/` Directory

### 2.1 Location and Discovery

`.asya/` behaves like `.git/` -- its presence marks an Asya project root.
Commands that require it walk up the directory tree until they find `.asya/`.
If not found, they fail with "run `asya init`."

`.asya/` can exist at any level in the file tree. A nested `.asya/` in a
subdirectory creates a sub-project (useful for monorepos with team boundaries).

```
my-project/
├── .asya/                        # Project root
│   ├── config.yaml               # Project-wide images config
│   └── manifests/                # Generated K8s manifests
│       ├── actors/               # Single-actor manifests
│       │   ├── file-creator.yaml
│       │   └── sentiment-analyzer.yaml
│       └── flows/                # Flow-generated manifests
│           └── order-processing/
│               ├── router-start.yaml
│               ├── router-check-type.yaml
│               ├── validate-order.yaml
│               ├── express-handler.yaml
│               └── payment-processor.yaml
├── src/
│   ├── team-a/
│   │   ├── .asya/                # Team A sub-project
│   │   │   └── config.yaml       # Team A's images config
│   │   └── e_commerce/
│   └── team-b/
│       ├── .asya/
│       │   └── config.yaml
│       └── ml_models/
```

### 2.2 Manifest Output Location

Generated manifests go into the **nearest** `.asya/manifests/` up the file
tree from the flow source file.

```
asya flow compile src/team-a/flows/order.py
  → writes to src/team-a/.asya/manifests/flows/order/

asya flow compile src/flows/simple.py
  → writes to .asya/manifests/flows/simple/  (root .asya/)
```

### 2.3 Config Composition via Walk-Up Recursive Merge

**Decision**: Implicit walk-up merge. No explicit `extend:` directive. The
CLI collects all `.asya/config.yaml` files from CWD (or flow file location)
up to the repo root (`.git/`), then merges them root-first. Like `.gitignore`
-- just place a file and it participates.

**Algorithm**:
```python
from omegaconf import OmegaConf

def load_effective_config(start_dir: Path) -> DictConfig:
    """Walk up from start_dir, collect and merge all .asya/config.yaml files."""
    configs = []
    current = start_dir.resolve()
    repo_root = find_git_root(current)

    while current >= repo_root:
        cfg_path = current / ".asya" / "config.yaml"
        if cfg_path.exists():
            cfg = OmegaConf.load(cfg_path)
            resolve_relative_paths(cfg, base_dir=cfg_path.parent.parent)
            configs.append(cfg)
        current = current.parent

    configs.reverse()  # root first, most local last
    return recursive_merge(configs)
```

**Recursive merge** handles dicts and lists differently:
- **Dicts**: deep merge (OmegaConf native). Local keys override ancestor keys.
- **Lists**: concatenate (append child entries after parent entries). No
  key detection, no overwrite. Duplicates are detected later at the Asya
  semantic layer (compile time), not at the merge layer.
- **Scalars**: replace (child wins).

**Three-layer architecture**:
1. **OmegaConf (syntactic)**: Load YAML, interpolation, strict fail on
   missing values. Zero knowledge of Asya.
2. **Merge (generic)**: Walk-up recursive merge. Dicts deep-merge, lists
   concatenate. Zero knowledge of Asya — no key field mappings, no
   overwrite logic.
3. **Asya (semantic)**: Schema validation, handler resolution. Detects
   duplicates in concatenated lists (e.g., two entries matching the same
   handler) and produces errors with source file locations.

```python
def recursive_merge(configs: list[DictConfig]) -> DictConfig:
    """Walk-up merge: dicts deep-merge, lists concatenate."""
    result = OmegaConf.create({})
    for cfg in configs:  # root first, local last
        for key in cfg:
            if is_list(result.get(key)) and is_list(cfg[key]):
                result[key] = list(result[key]) + list(cfg[key])  # append
            elif OmegaConf.is_dict(result.get(key)) and OmegaConf.is_dict(cfg[key]):
                result[key] = OmegaConf.merge(result[key], cfg[key])
            else:
                result[key] = cfg[key]  # scalars: replace
    return result
```

**Why append-only lists?** No key detection needed, no silent overwrites,
no merge-key configuration. The merge layer stays trivially simple. If two
configs define entries that resolve to the same handler, the Asya semantic
layer catches it at compile time with a clear error:
```
Error: duplicate image entry matching module 'langchain'
  defined in: /.asya/config.yaml:8
  and also in: src/team-a/.asya/config.yaml:3
  hint: remove one definition
```

**Debuggability of `var:` overrides** (dicts DO deep-merge, child wins):
verbose output traces the merge chain for every overridden value:
```
[config] var.image_registry:
  /.asya/config.yaml           → ghcr.io/org
  src/team-a/.asya/config.yaml → ghcr.io/team-a  (overrides)
  --var image_registry=...     → (not set)
  effective: ghcr.io/team-a
```

**Correctness requirements** for merge + interpolation:
1. **Resolve `./` paths BEFORE merge**: Each config's `./` relative paths
   must be resolved to absolute using that config file's directory as base.
   After merge, the source file info is lost.
2. **Interpolation resolves AFTER merge**: `${var.*}` references resolve
   lazily after the full effective config is assembled. This is why a
   child config can reference `${var.project_root}` even though `var` is
   only defined in the root config. OmegaConf's lazy resolution makes
   this work.
3. **`${arg.*}` resolves at command time**: After merge and after `var`
   resolution. Missing `arg` values are a hard error (no defaults).
4. **Root config MUST define `var:`**: The `var:` section is declared in
   Asya documentation and auto-generated by `asya init` in the root
   config.yaml. If `var:` is missing, OmegaConf will fail on any
   `${var.*}` reference -- this is correct fail-fast behavior.
5. **The OmegaConf/CLI layer is purely syntactic**: It performs
   interpolation and merge without knowing what `images`, `module`, or
   any other Asya-specific field means. Semantic validation (missing
   `module:`, unknown fields, etc.) happens at the Asya layer after
   OmegaConf produces the effective config.

**Example**:

```yaml
# /.asya/config.yaml (root, platform engineers)
var:
  project_root: "."                   # resolved to repo root at load time
  image_registry: ghcr.io/org

images:
  - module: langchain
    image: "ghcr.io/third-party/langchain:v2"
  - module: shared_utils
    path: "${var.project_root}/libs/shared_utils"
    image: "${var.image_registry}/shared:${arg.tag}"
    build:
      local: "docker build -t ${..image} ."
      remote: "docker build -t ${..image} . && docker push ${..image}"
```

```yaml
# src/team-a/.asya/config.yaml (team A)
# Root config is auto-discovered via walk-up merge

images:
  - module: e_commerce
    path: "./e_commerce"           # relative to THIS file
    image: "${var.image_registry}/ecom:${arg.tag}"
    build:
      local: "docker build -t ${..image} ."
```

**Path resolution**: Two styles coexist for the `path:` field:
- **`${var.project_root}/...`** -- repo-root-relative via interpolation.
  Stays as interpolation reference through merge, resolved lazily at use
  time. Portable across machines.
- **`./...`** -- file-relative, resolved to absolute before merge (necessary
  because source file info is lost after merge).

`var.project_root` is defined as `"."` in the root config.yaml. Since the
root config lives next to `.git/`, `"."` resolves to the repo root. Teams
inherit it via walk-up merge and can reference it as
`${var.project_root}/path`.

```
# Example: running from src/team-a/flows/
#
# Walk-up finds:
#   1. /.asya/config.yaml           (root)
#   2. src/team-a/.asya/config.yaml (local)
#
# Path resolution:
#   Root:   project_root: "."  →  resolved to /repo at load time
#   Root:   path: "${var.project_root}/libs/shared"  →  stays as interpolation
#   Team-A: path: "./e_commerce"  →  resolved to /repo/src/team-a/e_commerce
#
# Recursive merge (images list concatenated, root first):
```

**Effective config for team-a** (after walk-up merge):
```yaml
var:
  project_root: "/repo"          # resolved from root's "." (dict deep merge)
  image_registry: ghcr.io/org    # from root

images:
  # From root (concatenated first):
  - module: langchain
    image: "ghcr.io/third-party/langchain:v2"
  - module: shared_utils
    path: "${var.project_root}/libs/shared_utils"   # portable interpolation
    image: "${var.image_registry}/shared:${arg.tag}"
    build:
      local: "docker build -t ${..image} ."
      remote: "docker build -t ${..image} . && docker push ${..image}"

  # From team-a (appended after root):
  - module: e_commerce
    path: "/repo/src/team-a/e_commerce"  # resolved from team-a's "./e_commerce"
    image: "${var.image_registry}/ecom:${arg.tag}"
    build:
      local: "docker build -t ${..image} ."
```

**Why not explicit `extend:`?**
- OmegaConf has no YAML-level include/extend mechanism -- it's a value
  interpolation library, not a config composition one
- Hydra's `defaults:` list solves a different problem (experiment config
  group selection) and has no equivalent of our `var:` / `arg:` split
- Walk-up merge is simpler: no `extend:` paths to maintain, no cycles to
  detect, no cross-tree references to resolve
- `.gitignore`-style accumulation is familiar and predictable

---

## 3. `.asya/config.yaml` Schema

### 3.1 Design Principle

config.yaml contains ONLY the binding between Python code, images, and build
commands. It is NOT a build system -- it's a lookup table that Asya uses to
answer two questions:
1. "Which image does this handler belong to?" (compile time)
2. "How do I build this image?" (build time)

Asya works WITH build systems (Docker, apko, buildpacks, Shipwright, CI
pipelines), not as a replacement for them. Build tool configuration
(Dockerfiles, apko.yaml, requirements.txt, etc.) lives in the `path:`
directory, not in config.yaml.

### 3.2 Top-Level Structure

`images` is a **list** of entries, each identified by a `module:` field.
OmegaConf relative interpolation (`${..image}`) works within list items.
Walk-up merge unions lists by the `module:` key (see section 2.3).

```yaml
# .asya/config.yaml
# Ancestor configs are auto-discovered via walk-up merge

var:
  project_root: "."                     # resolved to repo root at load time
  image_registry: ghcr.io/org
  router_image: python:3.13-slim       # base image for generated router actors

images:
  # Python package → image + build commands
  - module: e_commerce
    path: "${var.project_root}/src/e-commerce-package"
    image: "${var.image_registry}/e-commerce:${arg.tag}"
    build:
      local: "docker build -t ${..image} ."
      remote: "docker build -t ${..image} . && docker push ${..image}"

  # GPU model with apko
  - module: gpu_models
    path: "${var.project_root}/src/gpu-models"
    image: "${var.image_registry}/gpu-models:${arg.tag}"
    build:
      local: "apko build apko.yaml ${..image}"
      remote: "shp build upload gpu-models --image ${..image}"

  # Third-party, never built
  - module: langchain
    image: "ghcr.io/third-party/langchain-actor:v2"
    # no path, no build — pre-built image

  # Dirty DS scripts (filesystem path)
  - module: "./src/notebooks/models"
    path: "./src/notebooks/models"
    image: "${var.image_registry}/notebook-models:${arg.tag}"
    build:
      local: "docker build -t ${..image} ."
```

**What's in**: module → path → image → build commands. That's it.

**What's NOT in**: Strategy names, lock file paths, requirements paths,
Python versions, builder configurations. Those are the build tool's concern
(inside the Dockerfile, apko.yaml, etc. in the `path:` directory).

### 3.3 Field Semantics

**`module:`** -- identifies Python code that maps to this image entry. Also
serves as the merge key for walk-up list union (section 2.3).

| Format | Example | Resolution |
|--------|---------|------------|
| Dotted module name | `e_commerce` | `importlib.util.find_spec()` at compile time |
| Dotted module.class | `e_commerce.models.LargeModel` | Same, more specific |
| Filesystem path | `"./src/scripts"` | Direct path matching (starts with `./`) |

**Matching rule**: Longest prefix wins. If `e_commerce` and
`e_commerce.models.LargeModel` both exist, a handler
`e_commerce.models.LargeModel.predict` matches the more specific entry.

**`path:`** -- directory where the build command runs (CWD). Relative paths
are resolved to absolute before merge. Can use `${var.project_root}/...`
for repo-root-relative paths (stays as interpolation through merge).

**`image:`** -- OCI image reference template with interpolation.

**`build:`** -- shell commands for building the image:
- `build.local` -- runs locally (build only, no push). Used by DS for
  iteration and testing. Example: `docker build -t ${..image} .`
- `build.remote` -- runs for remote/CI builds (build + push). Example:
  `docker build -t ${..image} . && docker push ${..image}`, or
  `shp build upload <name> --image ${..image}` for Shipwright.
- Entries without `build:` are never built by Asya (third-party images).

### 3.4 Variable Interpolation (OmegaConf-style)

Asya uses OmegaConf-inspired variable interpolation with dotted path
traversal:

| Syntax | Meaning | Example |
|--------|---------|---------|
| `${path.to.key}` | Absolute path from config root | `${var.image_registry}` |
| `${.sibling}` | Sibling at current level | `${.image}` (within same entry) |
| `${..sibling}` | Go up one level, access sibling | `${..image}` (from `build:` to entry's `image`) |
| `${arg.name}` | CLI `--arg` or `ASYA_CONFIG_ARG_NAME` env var | `${arg.tag}` |
| `${env:VAR}` | Raw environment variable | `${env:HOME}` |
| `${env:VAR,default}` | Env var with fallback | `${env:REGISTRY,ghcr.io/org}` |

**Resolution order**: Config-level references (`${var.*}`, `${.sibling}`)
are resolved first. Then `${arg.*}` and `${env:*}` are resolved at command
time (`asya actor build --arg tag=v1`).

**Two namespaces**:
- `${var.*}` -- static values defined in config. Inherited by child configs
  via walk-up merge. Typically set once in the root config.yaml.
- `${arg.*}` -- runtime values from CLI flags or env vars. No config-level
  definition — they exist only at runtime.

**Three override mechanisms** (all generic, zero Asya knowledge):

| Mechanism | Example | Scope |
|-----------|---------|-------|
| CLI flag | `--arg tag=v1`, `--var image_registry=x` | Single command |
| `ASYA_CONFIG_*` env var | `ASYA_CONFIG_ARG_TAG=v1`, `ASYA_CONFIG_VAR_IMAGE_REGISTRY=x` | Shell session |
| Config file `var:` | `var: {image_registry: ghcr.io/org}` | Project-wide |

**Env var naming convention**: `ASYA_CONFIG_<NAMESPACE>_<KEY>` where
namespace is `VAR` or `ARG`, key is UPPER_SNAKE_CASE of the config key.
```bash
# These are equivalent:
asya actor build foo --arg tag=v1
ASYA_CONFIG_ARG_TAG=v1 asya actor build foo

# Override a var from env (useful in CI):
export ASYA_CONFIG_VAR_IMAGE_REGISTRY=my-registry.io
asya actor build foo --arg tag=v1
```

**Precedence** (highest wins):
1. CLI `--var` / `--arg` flags
2. `ASYA_CONFIG_VAR_*` / `ASYA_CONFIG_ARG_*` env vars
3. Config file `var:` values (child > parent via walk-up merge)

**Strict resolution**: OmegaConf MUST fail with an error on any unresolved
interpolation. No silent empty string substitution. If `${arg.tag}` is
referenced but no source provides a value, the command fails immediately:
```
Error: unresolved interpolation '${arg.tag}'
  in: images[0].image = "${var.image_registry}/e-commerce:${arg.tag}"
  hint: pass --arg tag=<value> or set ASYA_CONFIG_ARG_TAG
```

**Example resolution**:
```yaml
var:
  project_root: "."
  image_registry: ghcr.io/org

images:
  - module: e_commerce
    path: "${var.project_root}/src/e-commerce"
    image: "${var.image_registry}/e-commerce:${arg.tag}"
    #       ^^^^^^^^^^^^^^^^^^^^^^ → ghcr.io/org  (from var)
    #                                              ^^^^^^^^^^^ → v1  (from --arg)
    # Final: ghcr.io/org/e-commerce:v1
    build:
      local: "docker build -t ${..image} ."
      #                       ^^^^^^^^^^ → ghcr.io/org/e-commerce:v1
      # ${..image} goes up from build → list item, gets resolved image
```

### 3.5 Build Commands Are Opaque

**Decision**: Asya treats build commands as opaque shell strings with
variable substitution. Asya has zero knowledge of what the command does.
Lock files, caching, validation, strategy selection are the build tool's
problem.

This means:
- Any build tool works (docker, apko, pack, kaniko, nix, bazel, custom)
- Future build tools work without Asya changes
- Platform engineers write the commands once in root config; DS just run
  `asya actor build`
- Asya is NOT a build system -- it's a command runner with context

**What about Shipwright remote builds?** For Shipwright, the `build.remote`
command is a `shp` CLI invocation. If deeper Shipwright integration is
needed later (generating Build CRDs from config.yaml), that can be added
as a plugin/extension without changing the core config schema.

### 3.6 Router Actor Default Image

Router actors use generated code (`routers.py`). They don't have their own
Python package — the compiler generates them. They need a base image to run
on.

**Design**: `var.router_image` in the root config.yaml specifies the default
base image for all generated actors. Router code is injected via ConfigMap
(same mechanism as `asya_runtime.py`), so no custom build step is needed.

```yaml
var:
  project_root: "."
  image_registry: ghcr.io/org
  router_image: python:3.13-slim     # base image for generated router actors
```

The compiler generates router manifests referencing `${var.router_image}`.
Since router code is small (a few KB of Python), ConfigMap injection is
sufficient.

If routers need additional Python dependencies (e.g., for custom condition
evaluation), users can:
1. Set `var.router_image` to a custom image with dependencies pre-installed
2. Or add an `images` entry for it and build it explicitly

### 3.7 Schema Validation (Two Levels)

Validation happens at two layers, matching the three-layer architecture
(section 2.3):

**Level 1 — OmegaConf (syntactic)**:
- Valid YAML
- All `${...}` interpolation references resolve (no dangling references)
- Types match (string, int, list, dict)
- Errors include file path, line number, and interpolation path

```
Error: unresolved interpolation '${var.registy}'
  in: .asya/config.yaml:7
  images[0].image = "${var.registy}/e-commerce:${arg.tag}"
  hint: did you mean '${var.image_registry}'?
```

**Level 2 — Asya (semantic)**:
- No unknown top-level keys (catch typos like `iamges:`)
- `build.local` / `build.remote` are valid shell commands (basic syntax check)
- `path:` directories exist on disk (when building)
- Image references in manifests resolve to an `images` entry (at compile time)
- **Duplicate detection in concatenated lists**: after walk-up merge
  concatenates lists (section 2.3), the Asya layer checks for entries that
  resolve to the same handler. This is a semantic check — the merge layer
  knows nothing about `module:` or handler resolution.

```
Error: duplicate image entry matching module 'langchain'
  defined in: /.asya/config.yaml:8
  and also in: src/team-a/.asya/config.yaml:3
  hint: remove one definition
```

```
Error: unknown top-level key 'iamges'
  in: src/team-a/.asya/config.yaml:5
  hint: did you mean 'images'?
```

Semantic validation runs after OmegaConf produces the effective config.
Both levels produce errors with source file location and actionable hints.

---

## 4. The Four Stages

### 4.1 Compile Time

**Input**: flow source (Python) + `.asya/config.yaml`
**Available**: Python interpreter (kernel or `--python`)
**Output**: router code + K8s manifests in `.asya/manifests/`

**Python environment detection** (for CLI mode):
1. Check `--python /path/to/python` flag (explicit)
2. Check active virtualenv (`VIRTUAL_ENV` / `sys.prefix != sys.base_prefix`)
3. Auto-detect from project tooling (in order):
   - `uv` -- if `uv.lock` or `[tool.uv]` in pyproject.toml → `uv run python`
   - `poetry` -- if `poetry.lock` → `poetry run python`
   - `pdm` -- if `pdm.lock` → `pdm run python`
   - `hatch` -- if `[tool.hatch]` in pyproject.toml → `hatch run python`
   - `conda`/`mamba` -- if `environment.yml` → `conda run python`
   - `pixi` -- if `pixi.lock` → `pixi run python`
   - `rye` -- if `.python-version` + `requirements.lock` → `rye run python`
4. Fail with "cannot resolve Python environment, use --python"

Asya does NOT fall back to bare `python3` on PATH -- that could silently
resolve to a wrong environment. Explicit is better.

**In Jupyter**: Use `sys.executable` from the running kernel. No `--python`
needed.

**Verbose output requirement**: All compile/build/deploy commands MUST be
maximally informative, showing exactly what resolved to what. No hidden
resolutions. Example:

```
$ asya flow compile flows/order_processing.py
[compile] Python: /home/user/.venv/bin/python (detected from VIRTUAL_ENV)
[compile] Config (walk-up merge):
           1. /.asya/config.yaml (root)
           2. src/team-a/.asya/config.yaml (local)
[compile] Handler: validate_order
           → import: e_commerce.validate.validate_order
           → file: /proj/src/e-commerce-package/e_commerce/validate.py
           → image entry: e_commerce
           → image: ghcr.io/org/e-commerce:${arg.tag}
[compile] Handler: express_handler
           → import: e_commerce.express.express_handler
           → file: /proj/src/e-commerce-package/e_commerce/express.py
           → image entry: e_commerce (same image)
[compile] Generated: .asya/manifests/flows/order-processing/
           → validate-order.yaml
           → express-handler.yaml
           → router-start.yaml
```

**Resolution chain**:
```
Flow source (AST parse)
    ↓ extract handler names
Handler refs: ["validate_order", "Model.predict"]
    ↓ Python import resolution (importlib.util.find_spec via detected Python)
File paths: ["/proj/src/e-commerce-package/e_commerce/validate.py", ...]
    ↓ match to config.yaml images list (longest module prefix wins)
Image entries: {"e_commerce" → ghcr.io/org/e-commerce:${arg.tag}}
    ↓ generate
Manifests: .asya/manifests/flows/<flow-name>/{router-*.yaml, actor-*.yaml}
Router code: compiled/routers.py (with resolve() calls)
```

**Important**: The compiler does NOT use PYTHONPATH to calculate module paths
(the current implementation does, but this is wrong). Instead, it uses Python's
own import system to resolve handler references to filesystem paths, then
matches those paths against config.yaml.

**Generated manifests** bind image + handler:
```yaml
# .asya/manifests/flows/order-processing/validate-order.yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: validate-order
spec:
  image: ghcr.io/org/e-commerce:${arg.tag}
  handler: e_commerce.validate.validate_order
  transport: rabbitmq
```

Same image for all handlers from the same package. Different `handler` field
for each actor.

**Future extension**: The compiler will detect `os.environ` / `os.getenv`
calls in handler code and generate exposed environment variable declarations
in the manifest.

### 4.2 Build Time

**Input**: `.asya/config.yaml` (read directly)
**Available**: Docker / apko / buildpacks. No live Python.
**Output**: OCI image (local or in registry)

CLI follows the `asya <noun> <verb>` pattern from the RFC
(`.aint/aints/asya-lab/rfc.md` section 5):

```bash
# Build a specific actor's image (--local = build only, no push)
asya actor build text-analyzer --local --arg tag=v1

# Build all images needed by a flow
asya flow build order-processing --local --arg tag=v1

# Remote build (build + push, or Shipwright) — enough to test on K8s
asya actor build text-analyzer --remote --arg tag=v1

# Variables via environment (useful in notebooks)
export ASYA_CONFIG_ARG_TAG=v1
asya flow build order-processing --local
```

**Two build flags**:
- `--local` → runs `build.local` command. Enough to test actors in local
  docker compose. Image stays on the machine, no registry push.
- `--remote` → runs `build.remote` command. Enough to test actors on K8s.
  Typically includes registry push (or Shipwright cluster build).

These flags interact with `--context` (see RFC `rfc.md`): `--context docker`
implies local builds, `--context k8s-stg` implies remote builds. The
`--local`/`--remote` flags are explicit overrides when context defaults
aren't sufficient.

**Resolution**:
- `asya actor build <actor-name> --local` → reads manifest to find image
  ref → matches image ref to config.yaml `images` entry → runs
  `build.local` command in the `path:` directory
- `asya actor build --remote` → same resolution but runs `build.remote`
- `asya flow build <flow-name>` → finds all actors in flow → deduplicates
  by image (multiple actors may share the same image) → builds each unique
  image once

No Python resolution happens at build time -- the `path:` value is taken
directly from config.yaml. Asya just runs the shell command with variable
substitution.

**Caching and skipping**: Since build commands are opaque, Asya has no
built-in caching or "skip if unchanged" logic. If a user needs conditional
builds, they can use `${arg.*}` to pass flags to the build tool:
```yaml
build:
  local: "docker build ${arg.cache_flag} -t ${..image} ."
  # asya actor build foo --local --arg cache_flag="--no-cache"
  # or: asya actor build foo --local  (cache_flag must be provided or fail)
```
OmegaConf default values for `arg` are not supported — missing args are a
hard error. If a build command needs optional flags, use `${env:VAR,default}`
instead (`${env:DOCKER_CACHE,}` resolves to empty string if unset).

**Note**: `asya actor compile` is also needed to generate manifests for
standalone actors (not part of a flow). Compilation is not flow-only --
any actor that Asya deploys needs a manifest in `.asya/manifests/`.

**Verbose output**:
```
$ asya actor build text-analyzer --local --arg tag=v1
[build] Actor: text-analyzer
[build] Image entry: e_commerce (from manifest image ref)
[build] Dir: /proj/src/e-commerce-package
[build] Image: ghcr.io/org/e-commerce:v1
[build] Command: docker build -t ghcr.io/org/e-commerce:v1 .
[build] Running in /proj/src/e-commerce-package ...
```

### 4.3 Deploy Time

**Input**: `.asya/manifests/*.yaml` (generated at compile time)
**Available**: kubectl / flux / argocd. No Python.
**Output**: Running pods in K8s

```bash
# Staging (imperative)
asya flow deploy order-processing --arg tag=v1
asya actor deploy text-analyzer --arg tag=v1

# Production (GitOps)
# 1. Commit .asya/manifests/ to git
# 2. Create PR
# 3. flux/argocd picks up and applies
```

The `--arg` / `ASYA_CONFIG_ARG_*` substitution is the same mechanism for
both build and deploy. A DS can `export ASYA_CONFIG_ARG_TAG=experiment-42`
in their notebook
and then run both `asya flow build` and `asya flow deploy` without repeating
the tag.

### 4.4 Runtime

**Input**: Running container with handler code
**Available**: Full Python environment inside the container
**Output**: Handler execution, envelope processing

- `asya_runtime.py` imports handler via `ASYA_HANDLER` env var
- Router actors use `resolve()` with `ASYA_HANDLER_*` env vars to map handler
  names to actor names
- Standard Asya sidecar-runtime protocol

---

## 5. Project Layouts

### 5.1 Clean Layout (Recommended)

Proper Python packages with `pyproject.toml`:

```
my-project/
├── .asya/
│   ├── config.yaml
│   └── manifests/
├── src/
│   └── e-commerce-package/           # Python package
│       ├── e_commerce/               # Importable module
│       │   ├── __init__.py
│       │   ├── validate.py
│       │   ├── express.py
│       │   ├── standard.py
│       │   └── payment.py
│       ├── pyproject.toml            # Package metadata
│       ├── requirements.txt          # or uv.lock
│       ├── apko.yaml                 # Build config (for apko strategy)
│       └── apko.lock.json            # Lock file (generated)
├── flows/
│   └── order_processing.py
└── pyproject.toml                    # Workspace root (uv workspace)
```

```yaml
# .asya/config.yaml
var:
  project_root: "."
  image_registry: ghcr.io/org

images:
  - module: e_commerce
    path: "${var.project_root}/src/e-commerce-package"
    image: "${var.image_registry}/e-commerce:${arg.tag}"
    build:
      local: "apko build apko.yaml ${..image}"
      remote: "shp build upload e-commerce --image ${..image}"
```

### 5.2 Dirty Layout (DS Experimentation)

Script directories without proper packaging:

```
experiments/
├── .asya/
│   ├── config.yaml
│   └── manifests/
├── models/
│   ├── bert_classifier.py
│   ├── utils.py
│   ├── exploration.ipynb
│   ├── requirements.txt
│   └── Dockerfile
```

```yaml
# .asya/config.yaml
images:
  - module: "./models"                # Filesystem path, not importable
    path: "./models"
    image: "ghcr.io/org/bert-models:${arg.tag}"
    build:
      local: "docker build -t ${..image} ."
      remote: "docker build -t ${..image} . && docker push ${..image}"
```

For the dirty layout, compilation from Jupyter uses the kernel's Python (which
has all the `sys.path` hacks already applied). For CLI, the user must either
create a minimal `pyproject.toml` or use the `./` filesystem path syntax.

---

## 6. Python Resolution at Compile Time

### 6.1 How It Works

The compiler uses Python's `importlib` to resolve handler references:

```python
# Compiler resolution (pseudocode)
import importlib.util
import subprocess

def resolve_handler(handler_ref: str, python_path: str) -> str:
    """Resolve handler ref to filesystem path."""
    # Split: "e_commerce.validate.validate_order"
    # Try progressively shorter module paths
    parts = handler_ref.split(".")
    for i in range(len(parts), 0, -1):
        module_name = ".".join(parts[:i])
        # Use the target Python interpreter
        result = subprocess.run(
            [python_path, "-c",
             f"import importlib.util; "
             f"spec = importlib.util.find_spec('{module_name}'); "
             f"print(spec.origin if spec else '')"],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            return result.stdout.strip()
    raise ValueError(f"Cannot resolve {handler_ref}")
```

### 6.2 Current Compiler Implementation (What Changes)

**Current** (`src/asya-cli/asya_cli/flow/compiler.py`):
- Uses `PYTHONPATH` to calculate module prefix from filename
- AST-only: no actual Python imports
- `ast.unparse(call.func)` extracts handler name as string

**Proposed changes**:
- Add `--python` flag to `asya flow compile`
- Auto-detect Python from venv / `uv run` / PATH
- Use `importlib.util.find_spec()` (via subprocess to target Python) to resolve
  handler refs to filesystem paths
- Match filesystem paths to `config.yaml` `images` entries
- Remove PYTHONPATH-based module path calculation

### 6.3 DS Anti-Patterns and Asya's Stance

Asya does NOT reproduce Python's hacky import resolution (`sys.path.append`,
etc.). Instead:

| If you use... | CLI mode | Notebook mode |
|---------------|----------|---------------|
| Clean packages (`pyproject.toml`) | Works | Works |
| `sys.path.append()` | Fails (use clean packages) | Works (kernel has hacks applied) |
| Relative imports | Works (if package structure) | Works |
| No `__init__.py` (namespace packages) | Works (importlib handles) | Works |
| `%cd` + path hacks | N/A | Works |
| Scripts without packages | Use `module: "./path"` in config.yaml | Works |

**Philosophy**: CLI requires discipline (clean packages). Notebooks are
forgiving (Python kernel handles resolution). If your code is importable in
your Python environment, Asya can resolve it.

---

## 7. Variable Substitution

All `asya actor/flow build/deploy` commands support OmegaConf-style variable
interpolation in config.yaml fields. See section 3.4 for the full syntax
reference.

**Setting variables** via CLI flags or `ASYA_CONFIG_*` env vars:
```bash
# CLI flags (single command)
asya actor build text-analyzer --arg tag=v1 --arg env=staging
asya actor build text-analyzer --var image_registry=my-registry.io

# Env vars (shell session — survives across commands)
export ASYA_CONFIG_ARG_TAG=v1
export ASYA_CONFIG_ARG_ENV=staging
asya actor build text-analyzer --local
asya actor deploy text-analyzer  # same variables, no repetition

# Override var from env (useful in CI)
export ASYA_CONFIG_VAR_IMAGE_REGISTRY=ci-registry.internal
asya flow build order-processing --local --arg tag=$CI_SHA
```

**In config.yaml**:
```yaml
var:
  project_root: "."
  image_registry: ghcr.io/org

images:
  - module: e_commerce
    image: "${var.image_registry}/e-commerce:${arg.tag}"
    #       ^^^^^^^^^^^^^^^^^^^^^^ var (resolved first)
    #                                    ^^^^^^^^^^ arg (resolved at command time)
    build:
      local: "docker build -t ${..image} ."
      #                       ^^^^^^^^^^ relative ref (goes up to sibling `image`)
```

**In notebooks**: DS can `export ASYA_CONFIG_ARG_TAG=experiment-42` once
and then call `asya actor build` and `asya actor deploy` without repeating
the tag.

**Precedence** (highest wins, see also section 3.4):
1. CLI `--var` / `--arg` flags
2. `ASYA_CONFIG_VAR_*` / `ASYA_CONFIG_ARG_*` env vars
3. Config file `var:` values (child > parent via walk-up merge)
- `${var.*}` and `${.sibling}` resolve before `${arg.*}` and `${env:*}`
- Missing `${arg.*}` with no source → hard error (see section 3.4)

---

## 8. Open Questions

1. ~~**Config merging semantics**~~: Resolved. Walk-up `OmegaConf.merge()`
   with root-first, local-wins ordering. No explicit `extend:`. See
   section 2.3.

2. ~~**Build strategy awareness vs generic CLI**~~: Resolved. Opaque shell
   commands with variable substitution. Asya has zero knowledge of what the
   command does. See section 3.5.

3. ~~**Router actor images**~~: Resolved. `var.router_image` in root
   config specifies the base image. Router code injected via ConfigMap
   (same as `asya_runtime.py`). See section 3.6.

4. **Lock file relationship**: How does `actor-image.lock` (designed in
   `research-seamless-build.md`) relate to strategy-specific lock files
   (`apko.lock.json`)? Since build commands are opaque, Asya can't manage
   lock files inside the build tool. `actor-image.lock` may track only the
   final image digest, not internal build reproducibility.

5. **Python interpreter caching**: At compile time, should Asya cache the
   import resolution results? Useful for large flows with many handlers
   from the same package.

6. **Module matching edge cases**: What if a handler's module doesn't match
   any entry in config.yaml? Error? Prompt for manual mapping? Auto-suggest
   based on filesystem proximity?

7. **Monorepo workspaces**: For `uv workspace` / multi-package monorepos,
   should config.yaml be workspace-aware? Or is the hierarchical `.asya/`
   approach sufficient?

8. **OCI-first deployment model**: Future mode where actors are deployed
   by pushing OCI artifacts (not K8s manifests). Door left open -- config.yaml
   schema is agnostic to deployment strategy. Needs design when GitOps is
   stable.

9. **`asya init` design**: What does `asya init` create? At minimum: root
   `.asya/config.yaml` with `var.project_root`, `var.image_registry`,
   `var.router_image`, and an empty `images:` list. To be designed.

10. **`asya actor compile` for standalone actors**: How does a standalone
    actor (not part of a flow) get compiled? What's the input — a plain
    Python file, a decorator, a YAML manifest? To be designed.

11. **Non-Python actors**: The current design assumes Python handlers.
    Go actors, shell script actors, or pre-built third-party images with no
    Python module need a different matching strategy. The `module:` field is
    Python-specific — may need a more generic identifier for non-Python
    actors in future.

12. **Opaque build commands completeness**: Opaque shell commands work well
    as an escape hatch and cover the common case (Dockerfile, apko, pack
    CLI). However, analysis of `research-no-dockerfile.md` and
    `research-seamless-build.md` reveals gaps for advanced scenarios:

    **What opaque commands handle well**:
    - Any local build tool (docker, apko, pack, kaniko, nix, bazel)
    - Simple CI pipelines (shell script runs the command)
    - Shipwright via `shp` CLI (`build.remote: "shp build upload ..."`)
    - Tool-specific caching via env vars/flags

    **Where opaque commands have limitations**:
    - **No lock file generation**: Asya can't hash build inputs because it
      doesn't know what they are. `actor-image.lock` can only track the
      final image digest, not input reproducibility (Strategy C from
      `research-seamless-build.md` requires input hashing).
    - **No CUDA auto-resolution**: Cog's compatibility matrices (PyTorch →
      CUDA version) require pre-build analysis. An opaque command can't
      leverage this — DS must manually specify CUDA.
    - **No build rendering**: `asya build render` (generate Dockerfile from
      structured intent for GitOps) is not possible with opaque commands.
    - **No multi-strategy portability**: Switching from docker to apko
      requires rewriting the command string, not just changing a strategy
      flag.

    **Mitigation**: These limitations are acceptable for v1 (GitOps focus).
    If structured build intent is needed later (CUDA auto-resolution,
    input hashing, build rendering), it can be added as an optional
    `build.intent:` field alongside the existing opaque `build.local`/
    `build.remote` commands — no schema break needed.

---

## Sources

- Current compiler implementation: `src/asya-cli/asya_cli/flow/compiler.py`
- Current parser: `src/asya-cli/asya_cli/flow/parser.py`
- Current codegen: `src/asya-cli/asya_cli/flow/codegen.py`
- Runtime handler resolution: `src/asya-runtime/asya_runtime.py`
- Python import system: `importlib.util.find_spec()` (PEP 302, PEP 451)
- apko lock file: `research-no-dockerfile.md` section 2.4
- Build strategies: `research-no-dockerfile.md` section 4
- Shipwright: `research-seamless-build.md` section 2.2
