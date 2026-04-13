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
│   ├── config.yaml               # root: templates, build, compiler, secrets, contexts
│   ├── config.compiler.rules.yaml  # Filename-to-key: compiler.rules (treat-as rules)
│   ├── compiler/
│   │   └── templates/            # Template files (NOT in config tree)
│   │       ├── actor.yaml        # Handler actor template ({{ key }} syntax)
│   │       ├── router.yaml       # Router actor template ({{ key }} syntax)
│   │       ├── configmap_routers.yaml  # ConfigMap template
│   │       └── kustomization.yaml     # Kustomization template
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

Output path is configurable via `compiler.manifests` in config.yaml (default:
`.asya/manifests`). The compiler creates the directory structure on first
`asya compile` invocation — `asya init` does NOT create it.

```yaml
compiler:
  manifests: ".asya/manifests"   # Base directory, relative to project root
```

The compiler appends flow-specific subdirectories in code:
`config.resolve_path("compiler.manifests") / flow_name`. The `actors/` and
`flows/<flow-name>/` subdirectories are created as needed:

```
asya compile src/team-a/flows/order.py
  → writes to src/team-a/.asya/manifests/flows/order/

asya compile src/flows/simple.py
  → writes to .asya/manifests/flows/simple/  (root .asya/)

asya compile --handler e_commerce.validate.validate_order
  → writes to .asya/manifests/actors/validate-order.yaml
```

### 2.3 Config Composition via Walk-Up Recursive Merge

**Decision**: Implicit walk-up merge. No explicit `extend:` directive. The
CLI collects all `.asya/config*.yaml` files from CWD (or flow file location)
up to the repo root (`.git/`), then merges them root-first. Like `.gitignore`
-- just place a file and it participates.

**Filename-to-key with dotted sections**: Files named `config.<section>.yaml`
are merged under the `<section>:` key, with dotted sections creating nested
structure. `config.yaml` itself is the root. Templates and other subdirectories
(`.asya/compiler/templates/`, `.asya/compose/`) are NOT loaded into the config
tree.

- `.asya/config.yaml` — root keys (always loaded)
- `.asya/config.compiler.rules.yaml` → `compiler.rules` in merged config
- `.asya/compiler/templates/*.yaml` — template files, NOT in config tree

**Algorithm**:
```python
from omegaconf import OmegaConf, ListMergeMode

def load_effective_config(start_dir: Path) -> DictConfig:
    """Walk up from start_dir, collect and merge all .asya/config*.yaml files."""
    configs = []
    current = start_dir.resolve()
    repo_root = find_git_root(current)

    while current >= repo_root:
        asya_dir = current / ".asya"
        if asya_dir.exists():
            cfg = load_asya_dir(asya_dir)
            configs.append(cfg)
        current = current.parent

    configs.reverse()  # root first, most local last
    return OmegaConf.merge(*configs)

def load_asya_dir(asya_dir: Path) -> DictConfig:
    """Load all config*.yaml from .asya/, apply filename-to-key convention."""
    result = OmegaConf.create({})
    for f in sorted(asya_dir.glob("config*.yaml")):
        cfg = OmegaConf.load(f)
        resolve_relative_paths(cfg, base_dir=asya_dir.parent)
        if f.name == "config.yaml":
            result = OmegaConf.merge(result, cfg)
        else:
            # config.compiler.rules.yaml → compiler.rules
            # Dotted sections create nested structure
            section = f.name.removeprefix("config.").removesuffix(".yaml")
            keys = section.split(".")
            target = result
            for key in keys[:-1]:
                if key not in target:
                    target[key] = OmegaConf.create({})
                target = target[key]
            target[keys[-1]] = cfg
    return result
```

**Merge semantics** (OmegaConf native with `ListMergeMode.EXTEND`):
- **Dicts**: deep merge (OmegaConf native). Local keys override ancestor keys.
- **Lists**: concatenate via `ListMergeMode.EXTEND` (append child entries
  after parent entries). No key detection, no overwrite. Duplicates are
  detected later at the Asya semantic layer (compile time), not at the
  merge layer.
- **Scalars**: replace (child wins).

**Two-layer architecture**:
1. **OmegaConf (syntactic)**: Load YAML, interpolation, merge with
   `ListMergeMode.EXTEND`, strict fail on missing values. Zero knowledge
   of Asya. This is the OmegaConf library, not "inspired by."
2. **Asya (semantic)**: Walk-up file discovery, filename-to-key convention,
   schema validation, handler resolution. Detects duplicates in concatenated
   lists (e.g., two entries matching the same handler) and produces errors
   with source file locations.

**Why append-only lists?** No key detection needed, no silent overwrites,
no merge-key configuration. The merge layer stays trivially simple.

**Duplicate detection** (Asya semantic layer, after merge): Each config list
has a key field used for dedup. Duplicate key across configs = error by
default. No last-writer-wins, no silent override.

| List | Key field | Fallback key |
|------|-----------|--------------|
| `build:` | `module:` | `path:` (for entries without `module:`, e.g. standalone scripts) |
| `compiler.rules:` | `match:` | — |

```
Error: duplicate build entry matching module 'langchain'
  defined in: /.asya/config.yaml:8
  and also in: src/team-a/.asya/config.yaml:3
  hint: remove or update one definition, or add 'override: true' to the child entry
```

**Explicit override**: A child entry can replace a parent entry with the same
key by setting `override: true`. Without the marker, duplicate = error.

```yaml
# src/team-a/.asya/config.yaml
build:
  - module: langchain
    override: true              # explicitly replaces root's langchain entry
    image: ghcr.io/team-a/langchain:v3
    command: "docker build -t ${.image} ."
```

This keeps the default behavior safe (accidental duplicates are caught) while
enabling monorepo teams to intentionally diverge from root configuration.
The `override: true` marker applies to all list types (`build:`,
`compiler.rules:`) — any entry with a key field supports it.

**Debuggability of overrides** (dicts DO deep-merge, child wins):
verbose output traces the merge chain for every overridden value:
```
[config] var.image_registry:
  /.asya/config.yaml           → ghcr.io/org
  src/team-a/.asya/config.yaml → ghcr.io/team-a  (overrides)
  --set var.image_registry=... → (not set)
  effective: ghcr.io/team-a
```

**Correctness requirements** for merge + interpolation:
1. **Resolve `./` paths BEFORE merge**: Each config's `./` relative paths
   must be resolved to absolute using that config file's directory as base.
   After merge, the source file info is lost. The config loader handles
   this automatically — `./` paths are relative to the project root
   (parent of `.asya/`).
2. **Interpolation resolves AFTER merge**: `templates.*` config references
   resolve lazily after the full effective config is assembled. This is
   why a child config can reference `${templates.namespace}` even though it's
   only defined in the root config. OmegaConf's lazy resolution makes
   this work.
3. **Colon resolvers (`${arg:*}`, `${env:*}`) resolve at command time**:
   After merge and after `templates.*` resolution. Missing `arg` values
   are a hard error (no defaults). Config is always fully resolved at
   load time — no two-phase initialization.
4. **Root config MUST define `templates:` constants**: Constants like
   `templates.namespace`, `templates.transport` are auto-generated by `asya init` in
   the root config.yaml. If a referenced key is missing, OmegaConf will
   fail on the interpolation -- this is correct fail-fast behavior.
5. **The OmegaConf/CLI layer is purely syntactic**: It performs
   interpolation and merge without knowing what `build`, `module`, or
   any other Asya-specific field means. Semantic validation (missing
   `module:`, unknown fields, etc.) happens at the Asya layer after
   OmegaConf produces the effective config.

**Example**:

```yaml
# /.asya/config.yaml (root, platform engineers)
templates:
  namespace: default
  transport: sqs
  router_image: "python:3.13-slim"
  max_replicas: 5

compiler:
  image_registry: ghcr.io/org

build:
  - module: langchain
    image: "ghcr.io/third-party/langchain:v2"
  - module: shared_utils
    path: "./libs/shared_utils"
    image: "${compiler.image_registry}/shared:${arg:tag}"
    command: "docker build -t ${.image} ."
```

```yaml
# src/team-a/.asya/config.yaml (team A)
# Root config is auto-discovered via walk-up merge

build:
  - module: e_commerce
    path: "./e_commerce"           # relative to project root
    image: "${compiler.image_registry}/ecom:${arg:tag}"
    command: "docker build -t ${.image} ."
```

**Path resolution**: All `./` paths in config are resolved relative to the
project root (parent of `.asya/`) by the config loader. This is automatic —
no explicit `project_root` variable needed.

```
# Example: running from src/team-a/flows/
#
# Walk-up finds:
#   1. /.asya/config.yaml           (root)
#   2. src/team-a/.asya/config.yaml (local)
#
# Path resolution (all ./ relative to project root):
#   Root:   path: "./libs/shared"  →  resolved to /repo/libs/shared
#   Team-A: path: "./e_commerce"   →  resolved to /repo/e_commerce
#
# Recursive merge (build list concatenated, root first):
```

**Effective config for team-a** (after walk-up merge):
```yaml
templates:
  namespace: default                 # from root
  transport: sqs                     # from root
  router_image: "python:3.13-slim"   # from root
  max_replicas: 5                    # from root

compiler:
  image_registry: ghcr.io/org        # from root

build:
  # From root (concatenated first):
  - module: langchain
    image: "ghcr.io/third-party/langchain:v2"
  - module: shared_utils
    path: "/repo/libs/shared_utils"  # resolved from root's "./libs/shared_utils"
    image: "${compiler.image_registry}/shared:${arg:tag}"
    command: "docker build -t ${.image} ."

  # From team-a (appended after root):
  - module: e_commerce
    path: "/repo/e_commerce"         # resolved from team-a's "./e_commerce"
    image: "${compiler.image_registry}/ecom:${arg:tag}"
    command: "docker build -t ${.image} ."
```

**Why not explicit `extend:`?**
- OmegaConf has no YAML-level include/extend mechanism -- it's a value
  interpolation library, not a config composition one
- Hydra's `defaults:` list solves a different problem (experiment config
  group selection) and has no equivalent of our top-level / `arg:` split
- Walk-up merge is simpler: no `extend:` paths to maintain, no cycles to
  detect, no cross-tree references to resolve
- `.gitignore`-style accumulation is familiar and predictable

### 2.4 `asya init`

**Behavior**: Scaffolds the `.asya/` directory using
[Copier](https://copier.readthedocs.io/). No interactive prompts by default —
like `git init`, not `npm init`. Idempotent: running `asya init` in a
directory that already has `.asya/` is a no-op with a message.

**Scaffolding engine**: Copier generates the project from a built-in template
bundled with the `asya-cli` package. Copier supports future template updates
(`copier update`) for migrating existing projects to new config schema
versions.

**What it creates**:

```
.asya/
├── config.yaml               # root: templates, build, compiler, secrets, contexts
├── config.compiler.rules.yaml  # Filename-to-key: compiler.rules (treat-as rules)
└── compiler/
    └── templates/             # Template files (NOT in config tree)
        ├── actor.yaml         # Handler actor template ({{ key }} syntax)
        ├── router.yaml        # Router actor template ({{ key }} syntax)
        ├── configmap_routers.yaml
        └── kustomization.yaml
```

With `--template <name>`:
```
.asya/
├── config.yaml
├── config.compiler.rules.yaml
└── compiler/
    └── templates/
        ├── actor.yaml
        ├── router.yaml
        ├── configmap_routers.yaml
        └── kustomization.yaml
flows/                          # generated by template
├── example_flow.py
└── actors/
    ├── summarizer.py
    └── classifier.py
```

**Available templates**:

| Template | What's generated |
|----------|-----------------|
| (none) | `.asya/` config files only |
| `minimal` | + simple flow with two actors |
| `full` | + multi-step flow, build entries, contexts configured |
| `agentic-minimal` | + minimal agentic flow (LLM + tool actor) |
| `agentic-full` | + full agentic flow (routing, streaming, human-in-the-loop) |

Templates are Copier templates bundled with `asya-cli`. New templates can be
added without changing the CLI.

The `manifests/` directory is NOT created by init — it appears on first
`asya compile` invocation (see section 2.2). This avoids empty directories
in the repo before compilation has ever run.

**Generated `config.yaml`**:

```yaml
# .asya/config.yaml
# Asya project configuration
# Docs: https://asya.sh/docs/config

templates:
  namespace: default               # TODO: set your namespace
  transport: sqs                   # or: nats, memory
  router_image: python:3.13-slim
  max_replicas: 5

compiler:
  image_registry: ghcr.io/OWNER    # TODO: set your registry
  routers: "./compiled"             # Base directory for router code
  manifests: ".asya/manifests"      # Base directory for generated manifests

build: []
  # - module: my_package
  #   path: "./src/my-package"
  #   image: "${compiler.image_registry}/my-package:${arg:tag}"
  #   command: "docker build -t ${.image} ."

# contexts: {}
  # stg:
  #   kubecontext: my-stg-cluster   # TODO: set your kubeconfig context
  #   namespace: "${templates.namespace}"
  # NOTE: contexts are K8s-only. Docker Compose uses `asya d up` (no context).

# default_context: stg
```

**Generated template files** (full AsyncActor CRD templates using `{{ key }}`
syntax, work out of the box — DS does not need to edit for basic flows):

`.asya/compiler/templates/actor.yaml` (handler actors):
```yaml
# AsyncActor manifest template for user handler actors
# {{ key }} placeholders filled by stamper via regex substitution
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "{{ actor_name }}"
  namespace: "{{ namespace }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"
    asya.sh/flow-role: "{{ flow_role }}"
spec:
  actor: "{{ actor_name }}"
  image: "{{ image }}"
  handler: "{{ handler }}"
  transport: "{{ transport }}"
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: "{{ max_replicas }}"
```

`.asya/compiler/templates/router.yaml` (compiler-generated routers):
```yaml
# AsyncActor manifest template for router actors
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "{{ actor_name }}"
  namespace: "{{ namespace }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"
    asya.sh/flow-role: "{{ flow_role }}"
spec:
  actor: "{{ actor_name }}"
  image: "{{ router_image }}"
  handler: "{{ handler }}"
  transport: "{{ transport }}"
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 2
```

**Design decisions**:
- **Copier scaffolding**: Template bundled with `asya-cli`. Copier enables
  future schema migrations via `copier update`. No interactive prompts by
  default.
- **Full templates out of the box**: Templates ship with complete AsyncActor
  CRDs so `asya compile` works immediately after init. DS never needs to edit
  `{{ key }}` placeholders — they are filled by the stamper.
- **Two actor templates**: `actor.yaml` for handler actors (uses `{{ image }}`
  from build config), `router.yaml` for compiler-generated routers (uses
  `{{ router_image }}` from templates section).
- **Contexts commented out**: `contexts:` section is present but commented
  out. Commands that need a context fail-fast with a helpful error pointing
  to the config. DS configures contexts when ready to deploy.
- **`--template` flag**: Generates sample flows and actor handlers. Multiple
  templates available (minimal, full, agentic-minimal, agentic-full).
  Extensible — new templates added without CLI changes.
- **Manifests created on first compile**: Output directory
  (`compiler.manifests`) is created on first `asya compile` invocation, not
  init. Keeps the repo clean until compilation actually runs.
- **Fully git-tracked**: No `.gitignore` inside `.asya/`. Everything is
  committed — config is source of truth, manifests are required for GitOps.

**CLI**:
```bash
asya init                        # creates .asya/ in current directory
asya init --template minimal     # + simple flow with two actors
asya init --template full        # + multi-step flow, build entries, contexts
asya init src/team-a             # creates src/team-a/.asya/ (sub-project)
```

**Error cases**:
- `.asya/` already exists → print "already initialized" and exit 0
- Not inside a git repo → warn but proceed (`.asya/` doesn't require git,
  but walk-up merge stops at `.git/` boundary)

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

`build` is a **list** of build entries, each identified by a `module:` field.
OmegaConf relative interpolation (`${.image}`) references siblings within the same list item.
Walk-up merge concatenates lists (see section 2.3). Duplicates by `module:`
(or `path:` for entries without `module:`) are detected at the semantic layer
and produce errors.

```yaml
# .asya/config.yaml
# Ancestor configs are auto-discovered via walk-up merge

templates:
  namespace: default
  transport: sqs
  router_image: python:3.13-slim           # base image for generated router actors
  max_replicas: 5

compiler:
  image_registry: ghcr.io/org
  routers: "./compiled"
  manifests: ".asya/manifests"

build:
  # Python package → image + build commands
  - module: e_commerce
    path: "./src/e-commerce-package"
    image: "${compiler.image_registry}/e-commerce:${arg:tag}"
    command: "docker build -t ${.image} ."

  # GPU model with apko
  - module: gpu_models
    path: "./src/gpu-models"
    image: "${compiler.image_registry}/gpu-models:${arg:tag}"
    command: "apko build apko.yaml ${.image}"
    # shipwright: buildpacks-v3  # future: on-cluster build

  # Third-party, never built
  - module: langchain
    image: "ghcr.io/third-party/langchain-actor:v2"
    # no path, no build — pre-built image

  # Dirty DS scripts (no module - just filesystem path)
  - path: "./src/notebooks/models"
    image: "${compiler.image_registry}/notebook-models:${arg:tag}"
    command: "docker build -t ${.image} ."
```

**What's in**: module → path → image → build command. That's it.

**What's NOT in**: Strategy names, lock file paths, requirements paths,
Python versions, builder configurations. Those are the build tool's concern
(inside the Dockerfile, apko.yaml, etc. in the `path:` directory).

### 3.3 Field Semantics

**`module:`** -- identifies Python code that maps to this build entry. Also
serves as the merge key for walk-up list union (section 2.3).

| Format | Example | Resolution |
|--------|---------|------------|
| Dotted module name/prefix | `e_commerce.models` | `importlib.util.find_spec()` at compile time |
| Dotted module.class | `e_commerce.models.LargeModel` | Same, more specific |

**Matching rule**: Longest prefix wins. If `e_commerce` and
`e_commerce.models.LargeModel` both exist, a handler
`e_commerce.models.LargeModel.predict` matches the more specific entry.

**`path:`** -- directory where the build command runs (CWD). All `./` relative
paths are resolved relative to the project root (parent of `.asya/`) by the
config loader. This is automatic — no explicit variable needed.

**`image:`** -- OCI image reference template with interpolation.

**`command:`** -- a single opaque shell string for building the image locally.
`asya build` runs the command (build only); `asya build --push` runs the
command and then pushes the image to the registry. Remote/on-cluster builds
(e.g. Shipwright) are a separate mechanism via the `shipwright:` config field
(future). CI ignores `command:` entirely and runs its own pipeline.
Example: `docker build -t ${.image} .`
- Entries without `command:` are never built by Asya (third-party images).

### 3.4 Variable Interpolation (OmegaConf)

Asya uses OmegaConf (the library, not "inspired by") for variable interpolation
with dotted path traversal:

| Syntax | Meaning | Example |
|--------|---------|---------|
| `${path.to.key}` | Absolute path from config root | `${templates.namespace}` |
| `${.sibling}` | Sibling reference within the same list item | `${.image}` (from `command` to entry's `image`) |
| `${arg:name}` | CLI `--arg` or `ASYA_ARG_NAME` env var | `${arg:tag}` |
| `${env:VAR}` | Raw environment variable | `${env:HOME}` |
| `${env:VAR,default}` | Env var with fallback | `${env:REGISTRY,ghcr.io/org}` |

**OmegaConf custom resolvers**: The colon (`:`) distinguishes external
resolvers from config tree traversal (dot `.`). This is OmegaConf's native
mechanism — not custom syntax:

- **Dot** (`${path.to.key}`) — walks the config tree. OmegaConf built-in.
- **Colon** (`${resolver:key}`) — calls a registered resolver function.
  OmegaConf built-in for `env:`, Asya registers `arg:`.

```python
# Asya registers one custom resolver at startup:
OmegaConf.register_new_resolver("arg", lambda key: cli_args[key])
# OmegaConf already provides: ${env:VAR} (oc.env)
```

**Resolution order**: `templates.*` config references (`${templates.key}`, `${.sibling}`)
are resolved first. Then `${arg:*}` and `${env:*}` are resolved at command time.
Config is always fully resolved at load time — no two-phase initialization.

**Two namespaces**:
- `templates.*` keys -- static values defined in config under `templates:`. Inherited by
  child configs via walk-up merge. Typically set once in the root config.yaml.
  These values are available as `{{ key }}` in template files.
- `${arg:*}` -- runtime values from CLI flags or env vars. No config-level
  definition — they exist only at runtime.

**Three override mechanisms** (all generic, zero Asya knowledge):

| Mechanism | Example | Scope |
|-----------|---------|-------|
| CLI flag | `--arg tag=v1`, `--set templates.namespace=x` | Single command |
| `ASYA_*` env var | `ASYA_ARG_TAG=v1`, `ASYA_TEMPLATES_NAMESPACE=x` | Shell session |
| Config file (`templates:`) | `templates: { namespace: default }` | Project-wide |

**Env var naming convention**: `ASYA_<NAMESPACE>_<KEY>` where
namespace is `ARG` for runtime args or `TEMPLATES` for template constants, key is
UPPER_SNAKE_CASE of the config key.
```bash
# These are equivalent:
asya build foo --arg tag=v1
ASYA_ARG_TAG=v1 asya build foo

# Override a template constant from env (useful in CI):
export ASYA_TEMPLATES_NAMESPACE=production
asya compile foo.flow.py
```

**Precedence** (highest wins):
1. CLI `--set` / `--arg` flags
2. `ASYA_*` env vars
3. Config file values (child > parent via walk-up merge)

**Pass-through vs strict resolution**: `${arg:*}` uses a pass-through
resolver — if no value is provided, the resolver returns the literal string
`${arg:tag}` instead of failing. This allows compile to produce manifests
with unresolved `${arg:*}` placeholders (resolved later at deploy time).

```python
def arg_resolver(key, default=MISSING):
    if key in cli_args:
        return cli_args[key]          # --arg tag=v1 → "v1"
    if default is not MISSING:
        return default                # ${arg:tag,latest} → "latest"
    return f"${{arg:{key}}}"          # no value → literal "${arg:tag}"
```

OmegaConf does not re-resolve strings returned by resolvers, so the literal
`${arg:tag}` passes through to the output unchanged.

**Fail-fast at point of use**: The command that **uses** a value must fail
if any interpolation remains unresolved. This applies to ALL resolver types:

| Resolver | Compile | Build | Deploy |
|----------|---------|-------|--------|
| `${templates.*}` | Resolved | Resolved | N/A |
| `${arg:*}` | **Pass-through if missing** | Fail if missing | Fail if missing |
| `${env:*}` | Resolved | Resolved | Resolved |

```
# asya k apply with unresolved ${arg:tag}:
Error: unresolved interpolation '${arg:tag}'
  in: validate-order.yaml → spec.workload...image
  hint: pass --arg tag=<value> or set ASYA_ARG_TAG
```

**Example resolution**:
```yaml
compiler:
  image_registry: ghcr.io/org

build:
  - module: e_commerce
    path: "./src/e-commerce"
    image: "${compiler.image_registry}/e-commerce:${arg:tag}"
  #       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ → ghcr.io/org  (from compiler)
  #                                                      ^^^^^^^^^^^ → v1  (from --arg)
  # Final: ghcr.io/org/e-commerce:v1
  command: "docker build -t ${.image} ."
  #                       ^^^^^^^^^^ → ghcr.io/org/e-commerce:v1
  # ${.image} is a sibling reference within the same list item, gets resolved image
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
  `asya build`
- Asya is NOT a build system -- it's a command runner with context

**What about Shipwright remote builds?** Shipwright is a separate config
mechanism via the `shipwright:` field (e.g. `shipwright: buildpacks-v3`),
not an opaque command. `asya build --remote` would create a Shipwright
BuildRun using this config. If deeper Shipwright integration is needed
later (generating Build CRDs from config.yaml), that can be added as a
plugin/extension without changing the core config schema.

### 3.6 Router Actor Default Image

Router actors use generated code (`routers.py`). They don't have their own
Python package — the compiler generates them. They need a base image to run
on.

**Design**: `templates.router_image` in the root config.yaml specifies the default
base image for all generated actors. Router code is injected via ConfigMap
(same mechanism as `asya_runtime.py`), so no custom build step is needed.

```yaml
templates:
  namespace: default
  transport: sqs
  router_image: python:3.13-slim       # base image for generated router actors
  max_replicas: 5
```

The compiler generates router manifests using the `router.yaml` template,
which references `{{ router_image }}`. Since router code is small (a few KB
of Python), ConfigMap injection is sufficient.

If routers need additional Python dependencies (e.g., for custom condition
evaluation), users can:
1. Set `templates.router_image` to a custom image with dependencies pre-installed
2. Or add a `build` entry for it and build it explicitly

### 3.7 Schema Validation (Two Levels)

Validation happens at two layers, matching the three-layer architecture
(section 2.3):

**Level 1 — OmegaConf (syntactic)**:
- Valid YAML
- All `${...}` interpolation references resolve (no dangling references)
- Types match (string, int, list, dict)
- Errors include file path, line number, and interpolation path

```
Error: unresolved interpolation '${registy}'
  in: .asya/config.yaml:7
  build[0].image = "${registy}/e-commerce:${arg:tag}"
  hint: did you mean '${compiler.image_registry}'?
```

**Level 2 — Asya (semantic)**:
- No unknown keys in reserved sections (`build:`, `compile:`) (catch typos)
- `command` is a valid shell command (basic syntax check)
- `path:` directories exist on disk (when building)
- Image references in manifests resolve to a `build` entry (at compile time)
- **Duplicate detection in concatenated lists**: after walk-up merge
  concatenates lists (section 2.3), the Asya layer checks for duplicate keys
  (`module:` or `path:` for `build:`, `match:` for `compiler.rules:`).
  Duplicate = error with source file locations. No last-writer-wins.

```
Error: duplicate build entry matching module 'langchain'
  defined in: /.asya/config.yaml:8
  and also in: src/team-a/.asya/config.yaml:3
  hint: remove one definition
```

```
Error: unknown key 'iamges' at top level
  in: src/team-a/.asya/config.yaml:5
  hint: did you mean 'build'?
```

Semantic validation runs after OmegaConf produces the effective config.
Both levels produce errors with source file location and actionable hints.

### 3.8 Naming Convention: Function Names vs K8s Names

Two naming domains exist:

| Domain | Convention | Examples | Used in |
|--------|-----------|----------|---------|
| **Python function** | underscores | `my_flow`, `handler_a` | Source code, `spec.handler`, router functions, `{{ flow_function }}` |
| **K8s / Asya** | hyphens | `my-flow`, `handler-a` | `metadata.name`, `asya.sh/flow` label, filenames, ConfigMap names, `{{ flow_name }}` |

**Conversion**: `_` → `-`. The compiler works with function names. The stamper
converts to K8s names for all output. `spec.handler` keeps the Python form.

**In code**: `flow_function` = Python name, `flow_name` = K8s name.

### 3.9 Compile and Output Configuration

**Constraint**: Stamped manifests are real K8s resources consumed by kustomize.
They MUST NOT contain unresolved interpolations. All values are resolved at
compile time.

Compilation produces BOTH router code and deployment files in a single stage.
There is no separate template stage.

| File path | Config key | What it configures |
|-----------|-----------|-------------------|
| `config.yaml` | (root) | `templates:`, `build:`, `compiler:` |
| `config.compiler.rules.yaml` | `compiler.rules` | Treat-as rules for AST analysis |
| `compiler/templates/actor.yaml` | (NOT in config) | Handler actor template with `{{ key }}` placeholders |
| `compiler/templates/router.yaml` | (NOT in config) | Router actor template with `{{ key }}` placeholders |
| `compiler/templates/configmap_routers.yaml` | (NOT in config) | Router code ConfigMap template |
| `compiler/templates/kustomization.yaml` | (NOT in config) | Kustomization template for all layers |

Template files are loaded by the stamper directly from disk, NOT part of the
OmegaConf config tree. Config provides values that fill `{{ key }}` placeholders
via regex substitution.

#### `compiler:` section (in config.yaml)

```yaml
compiler:
  image_registry: ghcr.io/org
  routers: "./compiled"           # Base directory, code appends flow_function
  manifests: ".asya/manifests"    # Base directory, code appends flow_name
```

#### `config.compiler.rules.yaml` (→ `compiler.rules`)

```yaml
# .asya/config.compiler.rules.yaml
# Loaded as: compiler.rules in the merged config
[]                              # treat-as rules (future, see research-compiler-knowledge-base.md)
```

#### `compiler/templates/actor.yaml` (template file, NOT in config)

Standalone YAML that looks exactly like the final output. On disk it's a
lintable CRD. The `{{ key }}` placeholders are filled per-actor during
compilation via regex substitution.

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "{{ actor_name }}"
  namespace: "{{ namespace }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"
    asya.sh/flow-role: "{{ flow_role }}"
spec:
  actor: "{{ actor_name }}"
  image: "{{ image }}"
  handler: "{{ handler }}"
  transport: "{{ transport }}"
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: "{{ max_replicas }}"
```

The `spec.env` and `data.routers.py` fields are set programmatically by the
stamper after template resolution. Complex structures (lists, multi-line
strings) don't belong in template syntax.

#### `TemplateContext` dataclass — compiler-output variables

Template placeholders (`{{ key }}`) are filled from three sources:

1. **Config `templates.*`** — all keys from `templates:` section (pre-resolved)
2. **Compiler output** — fixed set defined by `TemplateContext` dataclass
3. **CLI args** — `--arg key=value`, pre-resolved

```python
@dataclass
class TemplateContext:
    """Compiler-output variables available in templates.

    These are the values the compiler always computes per actor.
    Config values from `templates:` and CLI args are merged separately.
    """
    actor_name: str       # "validate-order"
    flow_name: str        # "order-processing"
    flow_function: str    # "order_processing"
    flow_role: str        # "entrypoint", "router", "processor"
    handler: str          # "e_commerce.validate.validate_order"
    image: str            # "ghcr.io/org/e-commerce:${arg:tag}"
```

These keys are reserved. If `templates.actor_name` exists in config, it's an
error at compile time.

Resiliency values (`spec.resiliency.*`) are placed directly at XR spec paths
via compiler rules (`assign-to: spec.*`). See `research-compiler-knowledge-base.md`.

#### Merge precedence for template values

Same semantics as Crossplane XRD compositions — overlays first, user last:

1. **Overlays** applied in order (last wins) — infrastructure defaults
   (transport, scaling, GPU, resource limits)
2. **Template body** applied on top — user's explicit per-project values

The template body MAY contain static defaults (e.g., `transport:`,
`scaling:`). These are the user's explicit intent and override any overlay
defaults. Overlays provide sensible platform defaults; the template body is
the final authority.

#### Output modes (render stage)

Output mode is a render-time concern (`asya show --mode`), not
compile-time. The `compiler.mode` field in config sets the default:
- **manifests** (default): Raw AsyncActor XR files (resolve `${arg:*}`)
- **helm**: values.yaml files for Helm chart
- **kustomize**: Patches against a kustomize base
- **docker-compose**: docker-compose.yaml with orchestrator + runtimes (no
  sidecar, no message queue — uses `asya-testing` package)

See `adr.compiler-template-not-helm.md` for why this is printf-level
substitution, not a template engine.

---

## 4. The Five Stages

### 4.1 Compile Time (`asya compile`) — Stage 1

**Input**: flow source (Python) + `.asya/config*.yaml`
**Available**: Python interpreter (kernel or `--python`)
**Output**: router code + compiled manifests (editable intermediate)

Compile extracts all information from Python AST into compiled manifests.
After compile, the source of truth shifts from Python files to these
manifests. The user can edit them (add env vars, change scaling) without
recompiling.

### 4.1a Render Time (`asya show`) — Stage 2

**Input**: compiled manifests + context/mode
**Output**: target-specific artifacts (K8s YAML, helm values, kustomize
patches, docker-compose.yaml)

Render is re-runnable: edit a compiled manifest → re-render → updated
artifacts. No Python recompilation needed. Mode defaults from
`compiler.mode` in config or context type, overridable with `--mode`.

### 4.1b Compile Time (continued) — Python resolution

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
$ asya compile flows/order_processing.py
[compile] Python: /home/user/.venv/bin/python (detected from VIRTUAL_ENV)
[compile] Config (walk-up merge):
           1. /.asya/config.yaml (root)
           2. src/team-a/.asya/config.yaml (local)
[compile] Handler: validate_order
           → import: e_commerce.validate.validate_order
           → file: /proj/src/e-commerce-package/e_commerce/validate.py
           → image entry: e_commerce
           → image: ghcr.io/org/e-commerce:${arg:tag}
[compile] Handler: express_handler
           → import: e_commerce.express.express_handler
           → file: /proj/src/e-commerce-package/e_commerce/express.py
           → image entry: e_commerce (same image)
[compile] Compiled manifests: .asya/manifests/order-processing/
           → validate-order.yaml
           → express-handler.yaml
           → router-start.yaml
[compile] Next: asya show order-processing
```

**Verbosity levels**:

| Flag | Level | What's shown |
|------|-------|-------------|
| `-q` / `--quiet` | Quiet | No output (exit code only) |
| (default) | Normal | Resolution chain, output files, commands run |
| `-v` / `--verbose` | Verbose | + config merge trace, file paths, interpolation |
| `-vv` | Very verbose | + AST analysis, rule matching, OmegaConf debug |
| `-vvv` | Debug | + full OmegaConf config dump, internal state |

**Resolution chain**:
```
Flow source (AST parse)
    ↓ extract handler names
Handler refs: ["validate_order", "Model.predict"]
    ↓ Python import resolution (importlib.util.find_spec via detected Python)
File paths: ["/proj/src/e-commerce-package/e_commerce/validate.py", ...]
    ↓ match to config.yaml build list (longest module prefix wins)
Image entries: {"e_commerce" → ghcr.io/org/e-commerce:${arg:tag}}
    ↓ generate (router code + deployment files in one pass)
Manifests: .asya/manifests/flows/<flow-name>/{router-*.yaml, actor-*.yaml}
Router code: compiled/routers.py (with resolve() calls)
```

**Important**: The compiler does NOT use PYTHONPATH to calculate module paths
(the current implementation does, but this is wrong). Instead, it uses Python's
own import system to resolve handler references to filesystem paths, then
matches those paths against config.yaml.

**Environment variable detection**: The compiler detects `os.environ` /
`os.getenv` calls in handler code via AST analysis (see `match: os` rule in
`research-compiler-knowledge-base.md`). Detected env var names are looked up
in the `secrets:` section of `config.yaml` for K8s sourcing (secretKeyRef).
Default values from `os.getenv("KEY", "default")` are captured automatically.
All detected env vars are set programmatically in `spec.env` by the stamper.

### 4.2 Build Time — Stage 3

**Input**: `.asya/config.yaml` (read directly)
**Available**: Docker / apko / buildpacks. No live Python.
**Output**: OCI image (local or in registry)

CLI follows the `asya <noun> <verb>` pattern from the RFC
(`.aint/aints/asya-lab/rfc.md` section 5):

```bash
# Build a specific actor's image (build only, image stays local)
asya build text-analyzer --arg tag=v1

# Build all images needed by a flow
asya build order-processing --arg tag=v1

# Build + push to registry — enough to test on K8s
asya build text-analyzer --push --arg tag=v1

# Variables via environment (useful in notebooks)
export ASYA_ARG_TAG=v1
asya build order-processing
```

**Build flags**:
- Default: `asya build` runs `command` (build only, image stays local).
  Enough to test actors in local docker compose.
- `--push`: `asya build --push` runs `command` + pushes the image to
  the registry. Enough to test actors on K8s.
- Future: `asya build --remote` creates a Shipwright BuildRun using the
  `shipwright:` config field (separate mechanism, not an opaque command).

These flags interact with `--context` (see RFC `rfc.md`): `--context stg`
implies `--push` (contexts are K8s-only; Docker uses `asya d *`). The
`--push` flag is an explicit override when context defaults aren't
sufficient.

**Resolution**:
- `asya build <actor-name>` → reads manifest to find image ref →
  matches image ref to config.yaml `build` entry → runs `command` in
  the `path:` directory
- `asya build --push` → same resolution, runs `command` + pushes image
- `asya build <flow-name>` → finds all actors in flow → deduplicates
  by image (multiple actors may share the same image) → builds each unique
  image once

No Python resolution happens at build time -- the `path:` value is taken
directly from config.yaml. Asya just runs the shell command with variable
substitution.

**Caching and skipping**: Since build commands are opaque, Asya has no
built-in caching or "skip if unchanged" logic. If a user needs conditional
builds, they can use `${arg:*}` to pass flags to the build tool:
```yaml
command: "docker build ${arg:cache_flag} -t ${.image} ."
# asya build foo --arg cache_flag="--no-cache"
# or: asya build foo  (cache_flag must be provided or fail)
```
OmegaConf default values for `arg` are not supported — missing args are a
hard error. If a build command needs optional flags, use `${env:VAR,default}`
instead (`${env:DOCKER_CACHE,}` resolves to empty string if unset).

**Note**: `asya compile --handler` generates manifests for standalone actors
(not part of a flow). Input is CLI-driven: `asya compile --handler
e_commerce.validate.validate_order --arg tag=v1`. The generated manifest
IS the persistent artifact — no actor list in config.yaml.

**Discovery for list commands**: `asya k status` show
a unified outer-join table across three sources: (1) local `.py` files with
`@actor`/`@flow` decorators (matched via compiler rules), (2) compiled
manifests in `.asya/manifests/`, (3) deployed state in current context
(K8s/Docker). Decorator scan walks the project root. See rfc.md section 5.9.

**Verbose output**:
```
$ asya build text-analyzer --arg tag=v1
[build] Actor: text-analyzer
[build] Image entry: e_commerce (from manifest image ref)
[build] Dir: /proj/src/e-commerce-package
[build] Image: ghcr.io/org/e-commerce:v1
[build] Command: docker build -t ghcr.io/org/e-commerce:v1 .
[build] Running in /proj/src/e-commerce-package ...
```

### 4.3 Deploy Time — Stage 4

**Input**: rendered artifacts (from stage 2)
**Available**: kubectl / docker compose / flux / argocd. No Python.
**Output**: Running pods (K8s) or containers (Docker Compose)

```bash
# K8s staging (imperative)
asya show order-processing --arg tag=v1   # render with resolved tag
asya k apply order-processing                   # kubectl apply

# K8s production (GitOps)
# 1. asya show order-processing --arg tag=v1
# 2. Commit rendered manifests to git, create PR
# 3. flux/argocd picks up and applies

# Docker Compose (local dev)
asya d up order-processing --arg tag=v1    # auto-compile + compose + docker compose up
```

The `--arg` / `ASYA_ARG_*` substitution is the same mechanism for
build, render, and deploy. A DS can `export ASYA_ARG_TAG=experiment-42`
in their notebook and reuse it across all commands.

### 4.4 Runtime — Stage 5

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
templates:
  namespace: default
  transport: sqs
  router_image: python:3.13-slim
  max_replicas: 5

compiler:
  image_registry: ghcr.io/org

build:
  - module: e_commerce
    path: "./src/e-commerce-package"
    image: "${compiler.image_registry}/e-commerce:${arg:tag}"
    command: "apko build apko.yaml ${.image}"
    # shipwright: buildpacks-v3  # future: on-cluster build
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
build:
  - module: "./models"                # Filesystem path, not importable
    path: "./models"
    image: "ghcr.io/org/bert-models:${arg:tag}"
    command: "docker build -t ${.image} ."
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
- Add `--python` flag to `asya compile`
- Auto-detect Python from venv / `uv run` / PATH
- Use `importlib.util.find_spec()` (via subprocess to target Python) to resolve
  handler refs to filesystem paths
- Match filesystem paths to `config.yaml` `build` entries
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

All `asya build/deploy` commands support OmegaConf-style variable
interpolation in config.yaml fields. See section 3.4 for the full syntax
reference.

**Setting variables** via CLI flags or `ASYA_*` env vars:
```bash
# CLI flags (single command)
asya build text-analyzer --arg tag=v1 --arg env=staging
asya build text-analyzer --set var.image_registry=my-registry.io

# Env vars (shell session — survives across commands)
export ASYA_ARG_TAG=v1
export ASYA_ARG_ENV=staging
asya build text-analyzer
asya k apply text-analyzer  # same variables, no repetition

# Override a compiler constant from env (useful in CI)
export ASYA_COMPILER_IMAGE_REGISTRY=ci-registry.internal
asya build order-processing --arg tag=$CI_SHA
```

**In config.yaml**:
```yaml
compiler:
  image_registry: ghcr.io/org

build:
  - module: e_commerce
    image: "${compiler.image_registry}/e-commerce:${arg:tag}"
    #       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ compiler (resolved first)
    #                                                  ^^^^^^^^^^ arg (resolved at command time)
    command: "docker build -t ${.image} ."
    #                       ^^^^^^^^^^ relative ref (goes up to sibling `image`)
```

**In notebooks**: DS can `export ASYA_ARG_TAG=experiment-42` once
and then call `asya build` and `asya k apply` without repeating
the tag.

**Two namespaces** (see section 3.4):
- `templates.*` keys -- config values (dot syntax, resolved first)
- `${arg:*}` -- CLI args (colon syntax, resolved at command time)

**Precedence** (highest wins, see also section 3.4):
1. CLI `--set` / `--arg` flags
2. `ASYA_*` / `ASYA_ARG_*` env vars
3. Config file values (child > parent via walk-up merge)
- `templates.*` keys and `${.sibling}` resolve before `${arg:*}` and `${env:*}`
- Config is always fully resolved at load time — no two-phase initialization
- Missing `${arg:*}` with no source → hard error (see section 3.4)

---

## 8. Open Questions

1. ~~**Config merging semantics**~~: Resolved. Walk-up `OmegaConf.merge()`
   with root-first, local-wins ordering. No explicit `extend:`. See
   section 2.3.

2. ~~**Build strategy awareness vs generic CLI**~~: Resolved. Opaque shell
   commands with variable substitution. Asya has zero knowledge of what the
   command does. See section 3.5.

3. ~~**Router actor images**~~: Resolved. `templates.router_image` key in root
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

9. ~~**`asya init` design**~~: Resolved. Static scaffold (like `git init`):
   creates `.asya/config.yaml` with full config (`var:` constants +
   `build` + `compile`). Output directory created on first
   `asya compile` invocation, not init. See section 2.4.

10. ~~**Standalone actor compilation**~~: Resolved.
    `asya compile --handler module.function` resolves handler → image
    and stamps config.template.yaml in one step. No separate template verb.

11. **Non-Python actors**: The current design assumes Python handlers.
    Go actors, shell script actors, or pre-built third-party images with no
    Python module need a different matching strategy. The `module:` field is
    Python-specific — may need a more generic identifier for non-Python
    actors in future.

12. ~~**Opaque build commands completeness**~~: **Resolved (v1: opaque only)**.
    Full evaluation against `research-no-dockerfile.md` and
    `research-seamless-build.md`:

    **What opaque commands handle well** (~80% of real usage):
    - Any CLI build tool: docker, apko, pack, kaniko, nix, bazel, custom
    - Shipwright remote builds via `shp build upload` CLI
    - CI pipelines (shell script runs the command)
    - Tool-specific caching via env vars/flags (`${env:DOCKER_CACHE,}`)
    - Both GitOps (template → commit → flux) and OCI-first (build → push →
      image automation) workflows
    - Future build tools work without Asya code changes

    **Known gaps for v1** (accepted):
    - **No `actor-image.lock` input hashing**: Asya can't compute
      `input_hash` because opaque commands don't declare their inputs.
      Lock file deferred to v2. For v1, `asya promote` copies source files
      without hash verification. Workaround: hash entire `path:` directory
      minus `.gitignore` patterns.
    - **No CUDA auto-resolution**: DS must manually determine CUDA version.
      Mitigated by standalone helper command (`asya resolve cuda
      --requirements requirements.txt`) that reads Cog's compatibility
      matrices — independent of build commands.
    - **No build rendering**: Can't generate Dockerfile from structured
      intent. Not needed for v1 (users write their own Dockerfiles).
    - **Shipwright Build CR lifecycle**: `shp build upload` requires
      pre-existing Build CR. One-time manual setup per actor. Can add
      `asya actor setup --builder shipwright` in v2.
    - **No skip-if-unchanged**: Asya always runs the build command. Tied to
      lock file gap — with `input_hash`, Asya could skip unchanged builds.

    **Not a real gap**:
    - **Multi-strategy portability**: Switching docker→apko requires
      rewriting the command string, but teams rarely switch strategies.
      `asya init --strategy apko` can scaffold the right commands.

    **v2 extension path** (no schema break): Optional `build.intent:` field
    alongside existing `command` under `build[]`.
    When `intent` exists,
    Asya can auto-generate commands, compute `input_hash`, resolve CUDA.
    When absent, falls back to opaque commands. Additive change — v1 configs
    remain valid.

13. ~~**`${arg:tag}` lifecycle per mode**~~: **Resolved**. Pass-through
    resolver: during compile, the `arg` resolver returns the literal string
    `${arg:tag}` when no value is provided (resolved if `--arg tag=v1` is
    given). The generated manifest may contain unresolved `${arg:*}`
    placeholders. The command that **uses** the value (deploy, build) must
    fail-fast if any interpolation is still unresolved — including `${arg:*}`
    and `${env:*}`. For GitOps (ArgoCD/Flux), pass `--arg` at compile time to
    produce fully resolved manifests.

14. **Custom Helm chart support**: The helm mode generates values.yaml
    files. If a team uses a custom chart with a different values schema,
    the templates must match that chart's structure. Should
    Asya validate templates against the chart's `values.schema.json`?

15. ~~**Environment variable injection**~~: **Resolved**. Env var names are
    detected via AST analysis (`os.environ`, `os.getenv`). Default values
    from `os.getenv("KEY", "default")` are captured. K8s sourcing (secretKeyRef)
    comes from `secrets:` section in `config.yaml`. The stamper sets
    `spec.env` programmatically after template resolution. Resiliency values go
    directly to XR spec paths via `assign-to:` rules, not through env vars.
    See `research-compiler-knowledge-base.md`.

16. ~~**Infrastructure defaults ownership**~~: **Resolved**. Same semantics as
    Crossplane XRD compositions: overlays are applied first (in order, last
    wins), then user template values apply on top. The template body MAY
    contain static defaults (transport, scaling) — they act as the user's
    explicit intent and override any overlay defaults. This means overlays
    provide sensible infrastructure defaults, and the template body is the
    final authority for per-project overrides.

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
