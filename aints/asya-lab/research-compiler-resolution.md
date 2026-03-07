# Research: Compiler Resolution and Build Context Mapping

**Date**: 2026-03-07
**Status**: Informational
**Context**: How the Asya compiler resolves Python handler references to build
contexts, and how `.asya/config.yaml` maps Python packages to images and build
strategies.

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
Python package → build context → image
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
│   ├── config.yaml               # Project-wide build-contexts
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
│   │   │   └── config.yaml       # Team A's build-contexts
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

### 2.3 Config Inheritance via `include:`

**Decision**: Explicit inheritance via `include:` (like `tsconfig.json`
`extends`). No implicit merging -- each config is standalone unless it
explicitly includes a parent.

```yaml
# src/team-a/.asya/config.yaml
include: /.asya/config.yaml          # include root config

build-contexts:
  - module: "e_commerce"
    context: "./e_commerce"           # relative to THIS file
    image: "${registry}/ecom:${tag}"  # ${registry} from included defaults
```

```yaml
# /.asya/config.yaml (root, platform engineers)
defaults:
  registry: ghcr.io/org
  build:
    strategy: apko

build-contexts:
  - module: "langchain"
    image: "ghcr.io/third-party/langchain:v2"
  - module: "shared_utils"
    context: "./libs/shared_utils"    # relative to THIS file (repo root)
    image: "${registry}/shared:${tag}"
```

**`include:` path syntax**:
- `/path` -- absolute from repo root (directory containing `.git/`)
- `./path` -- relative to the config file containing the `include:`

**Merge behavior**:
- `defaults:` -- deep merge; local values override included values
- `build-contexts:` -- union by `module:` key; if same `module:` appears in
  both, **local wins** (child overrides parent)
- Without `include:` -- config is fully standalone, no parent entries visible

**Path resolution**: All paths (`context:`, `build:` sub-paths) are relative
to the config file that **defines** them, not the file that includes them.
This means a root config entry `context: "./libs/shared_utils"` always
resolves to `{repo-root}/libs/shared_utils`, regardless of which team config
includes it.

```
# Example resolution:
#
# /.asya/config.yaml defines:
#   context: "./libs/shared_utils"  →  /libs/shared_utils
#
# src/team-a/.asya/config.yaml includes /.asya/config.yaml
# The shared_utils context still resolves to /libs/shared_utils
# NOT to src/team-a/libs/shared_utils
#
# Team A's own entry:
#   context: "./e_commerce"  →  src/team-a/e_commerce
```

**Effective config for team-a** (after include + merge):
```yaml
defaults:
  registry: ghcr.io/org          # from root
  build:
    strategy: apko               # from root

build-contexts:
  # From root (included):
  - module: "langchain"
    image: "ghcr.io/third-party/langchain:v2"
  - module: "shared_utils"
    context: "/libs/shared_utils"  # resolved from root's ./libs/shared_utils
    image: "ghcr.io/org/shared:${tag}"

  # From team-a (local):
  - module: "e_commerce"
    context: "src/team-a/e_commerce"  # resolved from team-a's ./e_commerce
    image: "ghcr.io/org/ecom:${tag}"
```

---

## 3. `.asya/config.yaml` Schema

### 3.1 Top-Level Structure

```yaml
# .asya/config.yaml

build-contexts:
  - module: "e_commerce"                     # Python importable name
    context: "./src/e-commerce-package"      # Filesystem root (relative to this file)
    image: "ghcr.io/org/e-commerce:${tag}"   # Image template with ${} variables
    build:
      strategy: apko                         # apko | buildpack | dockerfile
      config: apko.yaml                     # Relative to context
      requirements: requirements.txt         # Relative to context

  - module: "./src/notebooks/models"         # Filesystem path (starts with ./)
    context: "./src/notebooks/models"
    image: "ghcr.io/org/notebook-models:${tag}"
    build:
      strategy: dockerfile
      dockerfile: Dockerfile
      target: runtime
      args:
        PYTHON_VERSION: "3.12"

  - module: "langchain"                      # Third-party, never built
    image: "ghcr.io/third-party/langchain-actor:v2"
    # No context, no build
```

### 3.2 Field Semantics

**`module:`** -- identifies Python code that maps to this build context.

| Format | Example | Resolution |
|--------|---------|------------|
| Dotted module name | `"e_commerce"` | `importlib.util.find_spec()` at compile time |
| Dotted module.class | `"e_commerce.models.LargeModel"` | Same, more specific |
| Filesystem path | `"./src/scripts"` | Direct path matching (starts with `./`) |

**Matching rule**: Longest prefix wins. If `"e_commerce"` and
`"e_commerce.models.LargeModel"` both exist, a handler
`e_commerce.models.LargeModel.predict` matches the more specific entry.

**`context:`** -- filesystem root for build operations. Paths are relative to
the config.yaml file. This becomes the Docker build context, the apko working
directory, or the buildpack source directory.

**`image:`** -- OCI image reference template. Supports `${name}` variable
substitution. Variables can be set via:
- CLI: `--arg tag=v1 --arg env=staging`
- Environment: `ASYA_ARG_TAG=v1`, `ASYA_ARG_ENV=staging`

**`build:`** -- strategy-specific configuration. Paths within `build:` are
relative to `context:`.

### 3.3 Strategy-Specific Build Configuration

**apko**:
```yaml
build:
  strategy: apko
  config: apko.yaml              # apko config file
  lockfile: apko.lock.json       # apko lock file (generated by apko lock)
  requirements: requirements.txt  # pip deps (fed to melange or multi-stage)
```

**Buildpacks**:
```yaml
build:
  strategy: buildpack
  builder: paketobuildpacks/builder:base   # optional, default builder
  env:                                      # BP_ environment variables
    BP_CPYTHON_VERSION: "3.12"
```

**Dockerfile**:
```yaml
build:
  strategy: dockerfile
  dockerfile: Dockerfile          # Dockerfile path
  target: runtime                 # multi-stage target (optional)
  args:                           # --build-arg values
    PYTHON_VERSION: "3.12"
    CUDA_VERSION: "12.1"
```

### 3.4 Build Strategy: Teach or Generalize?

**Open question**: Should Asya have built-in knowledge of each build strategy
(apko, dockerfile, buildpack), or should it treat the build command as a
generic CLI command?

**Option A -- Built-in strategies** (current design):
```yaml
build:
  strategy: apko
  config: apko.yaml
```
Asya knows how to invoke `apko build`, `docker build`, `pack build`. Can
validate configs, generate lock files, manage flags.

**Option B -- Generic CLI command**:
```yaml
build:
  command: "apko build apko.yaml ${image}"
  # or:
  command: "docker build -f Dockerfile -t ${image} ."
```
Asya just runs the command. No strategy knowledge needed. More flexible
(supports any builder tool), but no validation, no lock file management.

**Option C -- Built-in strategies + CLI escape hatch**:
```yaml
build:
  strategy: apko         # Asya manages the build
  # or:
  strategy: custom
  command: "my-builder build --output ${image}"
```

**Consideration**: Remote build via Shipwright (see `research-seamless-build.md`)
would need strategy awareness to generate Build CRDs. A generic CLI command
can't easily translate to a Shipwright BuildSpec.

---

## 4. The Four Stages

### 4.1 Compile Time

**Input**: flow source (Python) + `.asya/config.yaml`
**Available**: Python interpreter (kernel or `--python`)
**Output**: router code + K8s manifests in `.asya/manifests/`

**Python environment detection** (for CLI mode):
1. Check `--python /path/to/python` flag (explicit)
2. Check active virtualenv (`VIRTUAL_ENV` / `sys.prefix != sys.base_prefix`)
3. Check `uv run` -- if project has `pyproject.toml`, use `uv run python`
4. Fall back to `python3` on PATH
5. Fail with "cannot resolve Python environment, use --python"

**In Jupyter**: Use `sys.executable` from the running kernel. No `--python`
needed.

**Resolution chain**:
```
Flow source (AST parse)
    ↓ extract handler names
Handler refs: ["validate_order", "Model.predict"]
    ↓ Python import resolution (importlib.util.find_spec via detected Python)
File paths: ["/proj/src/e-commerce-package/e_commerce/validate.py", ...]
    ↓ match to config.yaml build-contexts (longest prefix wins)
Build contexts: {"e_commerce" → ghcr.io/org/e-commerce:${tag}}
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
  image: ghcr.io/org/e-commerce:${tag}
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
**Output**: OCI image in registry

```bash
# Build a specific module's image
asya build e_commerce --arg tag=v1

# Build all images in config.yaml
asya build --all --arg tag=v1

# Variables via environment (useful in notebooks)
export ASYA_ARG_TAG=v1
asya build e_commerce
```

The build command reads config.yaml, finds the entry for `module: "e_commerce"`,
and executes the strategy-specific build in the `context` directory.

No Python resolution happens at build time -- the context path is taken directly
from config.yaml.

### 4.3 Deploy Time

**Input**: `.asya/manifests/*.yaml` (generated at compile time)
**Available**: kubectl / flux / argocd. No Python.
**Output**: Running pods in K8s

```bash
# Staging (imperative)
asya deploy --arg tag=v1
# → applies .asya/manifests/ with ${tag} substituted

# Production (GitOps)
# 1. Commit .asya/manifests/ to git
# 2. Create PR
# 3. flux/argocd picks up and applies
```

The `--arg` / `ASYA_ARG_*` substitution is the same mechanism for both build
and deploy. A DS can `export ASYA_ARG_TAG=experiment-42` in their notebook
and then run both `asya build` and `asya deploy` without repeating the tag.

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
build-contexts:
  - module: "e_commerce"
    context: "./src/e-commerce-package"
    image: "ghcr.io/org/e-commerce:${tag}"
    build:
      strategy: apko
      config: apko.yaml
      requirements: requirements.txt
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
build-contexts:
  - module: "./models"                # Filesystem path, not importable
    context: "./models"
    image: "ghcr.io/org/bert-models:${tag}"
    build:
      strategy: dockerfile
      dockerfile: Dockerfile
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
- Match filesystem paths to `config.yaml` build-contexts
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

Both `asya build` and `asya deploy` support `${name}` variable substitution
in `image:` and other template fields.

**Setting variables**:
```bash
# Via --arg flag
asya build e_commerce --arg tag=v1 --arg env=staging

# Via environment variables
export ASYA_ARG_TAG=v1
export ASYA_ARG_ENV=staging
asya build e_commerce
asya deploy  # same variables, no repetition
```

**In config.yaml**:
```yaml
image: "ghcr.io/org/e-commerce:${tag}"
# or with defaults:
image: "ghcr.io/org/e-commerce:${tag:-latest}"
```

**In notebooks**: DS can `export ASYA_ARG_TAG=experiment-42` once and then
call `asya build` and `asya deploy` without repeating the tag.

---

## 8. Open Questions

1. ~~**Config merging semantics**~~: Resolved. Explicit `include:` with
   union + local-wins merge. See section 2.3.

2. **Build strategy awareness vs generic CLI**: Should Asya have built-in
   knowledge of build strategies, or treat builds as generic CLI commands?
   See section 3.4. Remote Shipwright builds may require strategy awareness.

3. **Router actor images**: Router actors use generated code (`routers.py`).
   They either need their own build context or use ConfigMap injection
   (current approach for `asya_runtime.py`). How do they fit in config.yaml?

4. **Lock file relationship**: How does `actor-image.lock` (designed in
   `research-seamless-build.md`) relate to strategy-specific lock files
   (`apko.lock.json`)? Is `actor-image.lock` a wrapper, or does each
   strategy manage its own lock file?

5. **Python interpreter caching**: At compile time, should Asya cache the
   import resolution results? Useful for large flows with many handlers
   from the same package.

6. **Module matching edge cases**: What if a handler's module doesn't match
   any entry in config.yaml? Error? Prompt for manual mapping? Auto-suggest
   based on filesystem proximity?

7. **Monorepo workspaces**: For `uv workspace` / multi-package monorepos,
   should config.yaml be workspace-aware? Or is the hierarchical `.asya/`
   approach sufficient?

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
