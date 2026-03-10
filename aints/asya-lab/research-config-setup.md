# Asya Config Setup

**Date**: 2026-03-10
**Status**: Design (will become user documentation)

---

## 1. Overview

Asya uses a two-layer config architecture:

1. **Syntactic layer** (`ConfigStore`) -- generic OmegaConf loading. Walks
   directories, discovers `.asya/` dirs, loads and merges YAML files, resolves
   all interpolations, tracks file provenance. No Asya-specific concepts.

2. **Semantic layer** (`AsyaProject`) -- Asya-specific abstractions on top
   of the resolved config. Path resolution, template access, image resolution,
   deployment contexts.

```
 User YAML files          ConfigStore              AsyaProject
 ┌──────────────┐    ┌───────────────────┐    ┌──────────────────┐
 │ config.yaml  │    │ Walk-up discovery │    │ resolve_path()   │
 │ config.*.yaml│───>│ OmegaConf merge   │───>│ resolve_image()  │
 │ (multiple    │    │ ${env:} ${arg:}   │    │ template access  │
 │  .asya/ dirs)│    │ File provenance   │    │ contexts         │
 └──────────────┘    └───────────────────┘    └──────────────────┘
```

---

## 2. The `.asya/` Directory

### 2.1 Location and Discovery

`.asya/` marks an Asya project root (like `.git/` marks a git repo). Commands
walk up from the current directory to the git root, collecting every `.asya/`
directory they find. If no `.asya/` is found, they fail with
"run `asya init`."

Multiple `.asya/` directories are supported for monorepos. A nested `.asya/`
in a subdirectory creates a sub-project with its own config that inherits
from the parent.

```
my-project/
├── .git/
├── .asya/                          # Root project config
│   ├── config.yaml                 # Root config file
│   ├── config.compiler.rules.yaml  # → merges as compiler.rules
│   ├── compiler/
│   │   └── templates/              # Template files (NOT config)
│   │       ├── actor.yaml
│   │       ├── router.yaml
│   │       ├── configmap_routers.yaml
│   │       └── kustomization.yaml
│   └── manifests/                  # Generated output
│       └── <flow-name>/
│           ├── base/               # Regenerated on compile
│           ├── common/             # User patches (preserved)
│           └── overlays/           # Per-env overrides (preserved)
│
├── services/
│   └── payments/
│       ├── .asya/                  # Sub-project config
│       │   └── config.yaml         # Overrides root for this subtree
│       └── flows/
│           └── order.py
```

### 2.2 Walk-up Merge

When loading config, the system walks from the start directory up to the git
root, collecting all `.asya/` directories. Config files merge root-first
(outermost first, nearest wins):

```
git root .asya/config.yaml          <- base values
     └── services/.asya/config.yaml <- overrides for services/
         └── services/payments/.asya/config.yaml  <- overrides for payments/
```

**Merge rules**:
- Dicts: deep-merge (nested keys merge recursively)
- Lists: concatenate (`ListMergeMode.EXTEND`)
- Scalars: nearest wins (child overrides parent)

---

## 3. Config Files

### 3.1 Filename Convention

Config files live directly in `.asya/` (not in subdirectories). The filename
determines where the content merges into the config tree:

| File | Merges as |
|------|-----------|
| `config.yaml` | Root of config tree |
| `config.compiler.rules.yaml` | `compiler.rules` |
| `config.secrets.yaml` | `secrets` |
| `config.a.b.c.yaml` | `a.b.c` (arbitrary nesting) |

Dotted sections in the filename create nested dicts. This is purely syntactic
-- there is no difference between putting `compiler.rules` inline in
`config.yaml` and splitting it into `config.compiler.rules.yaml`. Splitting
is for human organization.

### 3.2 config.yaml

The root config file. All sections are optional.

```yaml
# .asya/config.yaml

templates:
  namespace: default
  transport: sqs
  router_image: "python:3.13-slim"
  max_replicas: 5

build:
  - module: e_commerce
    path: "./src/e-commerce"
    image: "ghcr.io/org/e-commerce:${arg:tag,latest}"
    command: "docker build -t ${.image} ${.path}"

compiler:
  routers: "./compiled"
  manifests: ".asya/manifests"
  image_registry: ghcr.io/org

secrets:
  OPENAI_API_KEY:
    secret: llm-secrets
    key: openai-api-key
  DB_PASSWORD:
    secret: database-creds
    key: password

contexts:
  stg:
    type: kubernetes
    kubecontext: my-stg-cluster
    namespace: "${templates.namespace}"
    gateway: https://gw.stg.internal
  prod:
    type: kubernetes
    kubecontext: my-prod-cluster
    namespace: prod
    gateway: https://gw.prod.internal
    readonly: true
  local:
    type: docker
    compose_output: ".asya/compose/"
    gateway: http://localhost:8080

default_context: stg
```

**Sections**:

| Section | Purpose |
|---------|---------|
| `templates` | Values available as `{{ key }}` in template files |
| `build` | Python package to OCI image mapping |
| `compiler` | Compiler paths and settings |
| `secrets` | K8s Secret references for env injection |
| `contexts` | Deployment targets (K8s clusters, Docker Compose) |

### 3.3 Interpolation Syntax

Config files use OmegaConf interpolation. Two resolver families:

| Syntax | Source | Example |
|--------|--------|---------|
| `${section.key}` | Cross-reference within config | `${templates.namespace}` |
| `${.sibling}` | Relative ref to sibling key | `${.image}` inside a build entry |
| `${env:VAR}` | Environment variable | `${env:HOME}` |
| `${arg:key}` | CLI `--arg key=value` | `${arg:tag}` |
| `${arg:key,default}` | CLI with fallback | `${arg:tag,latest}` |

All interpolations are resolved at load time. The resolved config contains
no unresolved values -- if a `${arg:key}` has no value and no default, loading
fails immediately with a clear error.

### 3.4 Path Resolution

Config values starting with `./` are resolved to absolute paths relative to
the project root (parent of the `.asya/` directory that contains the file).
This happens at load time, before merge.

```yaml
compiler:
  routers: "./compiled"        # -> /home/user/project/compiled
  manifests: ".asya/manifests" # -> /home/user/project/.asya/manifests
```

Values containing `${...}` interpolations are not path-resolved at this
stage (they're resolved later by OmegaConf).

### 3.5 config.compiler.rules.yaml

Compiler treat-as rules, offloaded from `config.yaml` when the list grows.
Both sources merge via list concatenation.

```yaml
# .asya/config.compiler.rules.yaml
- match: "tenacity.retry(stop=stop_after_attempt(X))"
  treat-as: config
  assign-to: spec.resiliency.retry.maxAttempts
  where:
    stop:
      stop_after_attempt:
        max_attempt_number: X

- match: "my_lib.helper"
  treat-as: inline
```

---

## 4. Template Files

Template files live in `.asya/compiler/templates/`. They are NOT part of the
config tree -- they are loaded on demand by the manifest templater and resolved
using `{{ key }}` substitution.

### 4.1 Template Syntax

Templates use `{{ key }}` placeholders. Resolution is regex string
replacement (`re.sub(r'\{\{\s*(\w+)\s*\}\}', ...)`) followed by
`yaml.safe_load()`. No Jinja2.

### 4.2 Template Context

The templater builds a flat context dict from two sources:

1. **Config `templates:` section** -- user-defined values (namespace,
   transport, router_image, max_replicas, and any custom keys)
2. **Compiler output** (`TemplateContext` dataclass) -- typed, per-actor
   values computed by the compiler

Compiler output keys are **reserved names** that override config values
if there's a collision:

| Key | Source | Example |
|-----|--------|---------|
| `actor_name` | Compiler | `"validate-order"` |
| `flow_name` | Compiler | `"order-processing"` |
| `flow_function` | Compiler | `"order_processing"` |
| `flow_role` | Compiler | `"entrypoint"`, `"handler"`, `"router"` |
| `handler` | Compiler | `"routers.start_order_processing"` |
| `image` | Compiler | `"ghcr.io/org/e-commerce:v1"` |

All other `{{ key }}` references resolve from `templates:` in config.

### 4.3 Template Files

#### actor.yaml (handler actors)

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

#### router.yaml (router actors)

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
  image: "{{ router_image }}"
  handler: "{{ handler }}"
  transport: "{{ transport }}"
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 2
```

#### configmap_routers.yaml

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: "{{ flow_name }}-routers"
  namespace: "{{ namespace }}"
  labels:
    asya.sh/flow: "{{ flow_name }}"
    asya.sh/managed-by: asya-compiler
```

The `data.routers.py` field is added programmatically by the templater.

#### kustomization.yaml

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
```

The `resources` list is added programmatically by the templater.

### 4.4 Programmatic Fields

Some manifest fields are NOT templated -- they are set by the templater in
code because their values come from compiler analysis, not user config:

| Field | Set by | Content |
|-------|--------|---------|
| `spec.env` | Templater | `ASYA_HANDLER_*` router mappings, detected env vars, secret refs |
| `data["routers.py"]` | Templater | Compiled router code |
| `resources` | Templater | List of generated YAML filenames |

### 4.5 Customizing Templates

Platform engineers customize templates to set infra-tier defaults:

```yaml
# Add to .asya/compiler/templates/actor.yaml:
spec:
  resiliency:
    retry:
      policy: exponential
      maxAttempts: "{{ default_retry_attempts }}"
```

Custom template variables must be defined in the `templates:` section:

```yaml
# .asya/config.yaml
templates:
  default_retry_attempts: 3
```

These defaults become part of `base/` and can be overridden per-actor via
kustomize patches in `common/`.

---

## 5. Manifest Output

### 5.1 Output Directory

Configurable via `compiler.manifests` (default: `.asya/manifests`). The
templater creates a subdirectory per flow:

```
.asya/manifests/
└── order-processing/           # flow_name (kebab-case)
    ├── README.md               # Layer documentation
    ├── base/                   # Layer 1: compiler output
    │   ├── AUTO-GENERATED.md
    │   ├── kustomization.yaml
    │   ├── asyncactor-start-order-processing.yaml
    │   ├── asyncactor-validate-order.yaml
    │   ├── asyncactor-payment-processor.yaml
    │   ├── asyncactor-end-order-processing.yaml
    │   └── configmap-routers.yaml
    ├── common/                 # Layer 2: shared patches
    │   └── kustomization.yaml  # resources: [../base]
    └── overlays/               # Layer 3: per-context
        ├── stg/
        │   └── kustomization.yaml  # resources: [../../common]
        └── prod/
            └── kustomization.yaml
```

### 5.2 Layer Lifecycle

| Layer | Created by | On recompile |
|-------|-----------|--------------|
| `base/` | `asya compile` | Fully regenerated (wiped and recreated) |
| `common/` | `asya compile` (first run) | Preserved -- user patches survive |
| `overlays/<ctx>/` | `asya compile` (first run) | Preserved -- user patches survive |

### 5.3 Applying Manifests

```bash
# Apply to staging context
asya k apply order-processing --context stg

# Under the hood: kustomize build overlays/stg/ | kubectl apply
```

---

## 6. Monorepo Support

### 6.1 Config Inheritance

In a monorepo, each team can have its own `.asya/` directory. Config merges
root-first:

```
my-monorepo/
├── .asya/
│   └── config.yaml              # Org defaults
│       templates:
│         transport: sqs
│         namespace: shared
│       compiler:
│         image_registry: ghcr.io/org
│
└── services/
    └── payments/
        ├── .asya/
        │   └── config.yaml      # Team overrides
        │       templates:
        │         namespace: payments    # Override org default
        │
        └── flows/
            └── order.py
```

When compiling `services/payments/flows/order.py`, the effective config is:

```yaml
templates:
  transport: sqs              # from root .asya/
  namespace: payments          # overridden by payments/.asya/
compiler:
  image_registry: ghcr.io/org  # from root .asya/
```

### 6.2 Template Inheritance

Template files (`.asya/compiler/templates/`) do NOT merge -- the nearest
`.asya/` directory's templates win entirely. If `services/payments/.asya/`
has no `compiler/templates/` directory, the root's templates are used.

---

## 7. Config Provenance

The config system tracks which file contributed each value. This is surfaced
in CLI output for debugging:

```
$ asya config get templates.namespace -v
payments
  [.] Defined in:    /home/user/monorepo/.asya/config.yaml (value: shared)
  [.] Overridden in: /home/user/monorepo/services/payments/.asya/config.yaml (value: payments)
```

Provenance is tracked at the syntactic layer -- every loaded file is stored
as a `Path -> DictConfig` mapping before merge.

---

## 8. Naming Convention

Two naming domains:

| Domain | Convention | Examples | Used in |
|--------|-----------|----------|---------|
| Python function | underscores | `my_flow`, `handler_a` | Source code, `spec.handler`, `{{ flow_function }}` |
| K8s / Asya | hyphens | `my-flow`, `handler-a` | `metadata.name`, labels, filenames, `{{ flow_name }}`, `{{ actor_name }}` |

**Conversion**: replace `_` with `-`. The compiler works with Python names;
the templater converts to K8s names for all output.

---

## 9. Implementation Architecture

### 9.1 ConfigStore (syntactic layer)

`asya_lab/config/store.py`

Responsibilities:
- Walk up from start_dir to git root, find all `.asya/` directories
- Load `config.yaml` and `config.*.yaml` from each (filename-to-key nesting)
- Resolve `./` paths to absolute paths relative to each file's project root
- Merge all configs (root-first, `ListMergeMode.EXTEND`)
- Register and run `${env:*}` and `${arg:*}` resolvers
- Track file provenance (`sources: dict[Path, DictConfig]`)
- Return a fully resolved `DictConfig` with no unresolved values

Does NOT know about: templates, actors, flows, K8s, kustomize.

### 9.2 AsyaProject (semantic layer)

`asya_lab/config/project.py`

Responsibilities:
- Wrap `ConfigStore` with Asya-specific methods
- `resolve_path(dotted_key)` -- config value to absolute Path
- Template path accessors (`actor_template_path`, `router_template_path`, etc.)
- `build_template_context()` -- flat dict from `templates:` section
- `resolve_image(handler_name)` -- handler to container image reference
- `get_contexts()` -- deployment context names
- `explain(key)` -- provenance for verbose CLI output

### 9.3 ManifestTemplater

`asya_lab/compiler/templater.py` (renamed from `stamper.py`)

Responsibilities:
- Load and resolve `{{ key }}` templates
- Generate kustomize directory structure (base/common/overlays)
- Collect actor metadata from compiler output
- Build `spec.env` programmatically
- Write YAML manifests

Takes `AsyaProject` for all config access.

---

## 10. `asya init`

Creates the `.asya/` directory with default config and templates:

```bash
$ asya init
[+] Created .asya/config.yaml
[+] Created .asya/compiler/templates/actor.yaml
[+] Created .asya/compiler/templates/router.yaml
[+] Created .asya/compiler/templates/configmap_routers.yaml
[+] Created .asya/compiler/templates/kustomization.yaml
[+] Created .asya/config.compiler.rules.yaml
[+] Created .asya/manifests/
[+] Updated .gitignore
```

Idempotent -- skips files that already exist, never overwrites user changes.
