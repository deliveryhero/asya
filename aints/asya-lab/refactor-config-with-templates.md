# ADR: Config & Template System Refactor

## Status

Proposed

## Context

The current `.asya/` config system has three intertwined design issues:

1. **Directory-to-key convention** recursively loads all subdirectories into the
   OmegaConf config tree. `.asya/compiler/templates/actor.yaml` becomes
   `compiler.templates.actor` in config — but no code reads from that path.
   The stamper loads template files directly from disk. Dead complexity.

2. **`${dynamic:*}` in config.yaml** (`compiler.manifests: ".asya/manifests/${dynamic:flow_name}"`)
   forces two-phase config initialization: load first, supply dynamic values
   later via `with_values()`. This requires `ConfigNotFinalizedError`,
   `_activate()`, `_raise_if_unresolved()`, `unresolved()` — all to handle
   the gap between "config loaded" and "config usable".

3. **`${dynamic:*}` in templates** mixed with OmegaConf interpolation creates
   hacks: dummy placeholder values (`env="[]"`, `resources="[]"`,
   `router_code=""`), global `_set_active_loader` state, and a wrapper trick
   (`{"var": ..., "_tmpl": template}`) so `${var.namespace}` resolves inside
   templates that aren't part of the config tree.

## Decision

### Three file categories

| Category | Location | Syntax | In config tree? |
|---|---|---|---|
| **Config** | `config.yaml`, `config.<section>.yaml` | OmegaConf: `${templates.*}`, `${env:*}`, `${arg:*}` | Yes, always fully resolved |
| **Templates** | `.asya/compiler/templates/*.yaml` | `{{ key }}` (regex substitution) | No |
| **Rules** | `config.compiler.yaml` | Static YAML (no interpolation) | Yes, under `compiler.rules` |

### Config is always fully resolved

No `${dynamic:*}` in config. Paths are base directories:

```yaml
# .asya/config.yaml
templates:
  namespace: default
  transport: sqs
  router_image: "python:3.13-slim"
  max_replicas: 5

compiler:
  routers: "./compiled"
  manifests: ".asya/manifests"
  image_registry: "ghcr.io/my-org"
```

Code appends flow-specific suffixes:

```python
manifests_dir = config.resolve_path("compiler.manifests") / flow_name
routers_dir = config.resolve_path("compiler.routers") / flow_function
```

No `with_values()`, no `ConfigNotFinalizedError`, no two-phase initialization.
Config loads, resolves all interpolations, done.

### `templates:` section replaces `var:`

The config section `var:` is renamed to `templates:`. Its purpose is explicit:
**these values are available as `{{ key }}` in template files**. The section
name matches the directory name (`.asya/compiler/templates/`), making the
connection obvious.

Values in `templates:` participate in walk-up merge as before — a child
`.asya/config.yaml` can override `templates.namespace`.

Other config values (`compiler.image_registry`) are NOT template variables —
they're consumed by stamper code directly.

### `project_root` dropped

The `./` prefix in config paths is resolved relative to the project root
(parent of `.asya/`) by the config loader. This already works. No need for
an explicit `project_root` variable.

### Two actor templates: router vs handler

Templates split by actor role:

- **`router.yaml`** — for compiler-generated router actors. Uses
  `{{ router_image }}`, has lower scaling defaults, gets ConfigMap mounted.
- **`actor.yaml`** — for user handler actors. Uses `{{ image }}`,
  user-configurable `{{ max_replicas }}`.

### Template syntax: `{{ key }}` with regex

Templates use `{{ key }}` for ALL values — both config-derived and
compiler-output. Resolution is simple string replacement via regex
(`re.sub(r'\{\{\s*(\w+)\s*\}\}', ...)`). No Jinja2 dependency.

The stamper builds a single flat context dict from three sources:

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
    actor_name: str
    flow_name: str
    flow_function: str
    flow_role: str
    handler: str
    image: str
```

Collision rule: compiler output keys (defined by `TemplateContext`) are
reserved. If `templates.actor_name` exists in config, it's an error at
compile time.

### Template resolution flow

1. Read template file as string
2. `re.sub(r'\{\{\s*(\w+)\s*\}\}', lambda m: context[m.group(1).strip()], text)`
3. `yaml.safe_load(result)` to get a dict
4. Stamper adds programmatic fields (`env`, `data.routers.py`, `resources`)

No OmegaConf for templates. No wrapper hack. No dummy values. No
`_set_active_loader` for template resolution.

### Programmatic fields

Some manifest fields are complex structures (lists, multi-line strings) that
don't belong in template syntax. The stamper sets them after template
resolution:

| Field | In template? | Set by stamper |
|---|---|---|
| `spec.env` | No | `manifest["spec"]["env"] = actor.env` |
| `data.routers.py` | No | `cm["data"]["routers.py"] = router_code` |
| `resources` | No | `kust["resources"] = sorted(resources)` |

### Directory-to-key convention dropped

`load_asya_dir()` no longer recursively walks subdirectories. Config loading:

1. `config.yaml` — root config (unchanged)
2. `config.<section>.yaml` — filename-to-key with dotted section support
   (e.g., `config.compiler.yaml` loads existing key `rules` under config's `compiler`)
3. Subdirectories (`compiler/templates/`, `manifests/`, `compose/`) are NOT
   loaded into config

The `_load_directory_recursive()` function is removed.

### Rules location

Rules move from `.asya/compiler/rules.yaml` to `.asya/config.compiler.yaml`
(filename-to-key convention). Content unchanged — static YAML list.

### `${dynamic:*}` resolver removed

The `dynamic` OmegaConf resolver is removed from the codebase. The
`_resolve_dynamic` function, the `dynamic` resolver registration, and all
`${dynamic:*}` references in config and templates are gone.

The `arg` and `env` resolvers remain — they're used in config.yaml for
values like `${arg:tag}` and `${env:ASYA_NAMESPACE}`.

### `FlowContext` retained

`FlowContext` dataclass stays. It's used for:

- Computing path suffixes: `config.resolve_path("compiler.manifests") / ctx.flow_name`
- Providing compiler-output values to template context (via `dataclasses.asdict()`)

But it no longer interacts with config resolution — no `with_values()`.

## Template files after refactor

### `.asya/compiler/templates/actor.yaml`

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

### `.asya/compiler/templates/router.yaml`

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

### `.asya/compiler/templates/configmap_routers.yaml`

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

No `data` section — stamper adds `data.routers.py` programmatically.

### `.asya/compiler/templates/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
```

No `resources` — stamper adds it programmatically.

## What changes

### Code changes

| File | Change |
|---|---|
| `config/config.py` | Remove `_load_directory_recursive`, directory-to-key. Add dotted section support in filename-to-key. Remove `${dynamic:*}` resolver. Remove `with_values()`, `_activate()`, `_raise_if_unresolved()`, `unresolved()`, `ConfigNotFinalizedError`. Simplify `resolve_path()`. Remove `dynamic_values` from `ConfigLoader`. |
| `config/__init__.py` | Remove `ConfigNotFinalizedError` export. |
| `compiler/stamper.py` | Template resolution via `{{ key }}` regex. Build flat context from config `templates.*` + compiler output + args. Remove `_set_dynamic_values()`, `_base_dynamic_values`, wrapper hack, dummy values. Split router/actor templates. Add `TemplateContext` dataclass. |
| `init.py` | Update default config (`var:` to `templates:`, drop `project_root`, move `image_registry`/`router_image`). Update template strings to `{{ key }}` syntax. Move rules to `config.compiler.yaml`. Add `router.yaml` template. |
| `compile_cli.py` | `config.resolve_path(...) / flow_name` instead of `config.with_values(ctx).resolve_path(...)`. |
| `flow_cli.py` | Same path simplification. `ConfigLoader` no longer takes `dynamic_values`. |
| `build_cli.py` | Same path simplification. |
| `expose_cli.py` | Same. Read namespace from `config.templates.namespace`. |
| `show_cli.py` | Same path simplification. |
| `status_cli.py` | Same. |
| `k_cli.py` | Same. |

### Test changes

- All test fixtures writing `config.yaml` with `${dynamic:flow_name}` updated
  to plain `compiler.manifests: ".asya/manifests"`.
- `TestDirectoryToKey` removed, replaced with dotted section tests.
- `test_dynamic_resolver_outside_compile` removed.
- Stamper tests: template fixtures updated to `{{ key }}` syntax.
- Init tests: updated for new config format and file locations.

### Doc changes

- `rfc.md` sections 7.2-7.7, 8.1: template syntax, resolver list, naming
  conventions, compile pipeline description.
- `research-compiler-resolution.md` sections 2-3: config schema, template
  syntax, variable interpolation, directory structure.

## Consequences

- Config is always fully resolved at load time — simpler mental model
- Templates are clearly separate from config — no confusion about what's loaded where
- One template syntax (`{{ key }}`) — no mixing OmegaConf and custom resolvers
- Compiler output variables are typed and documented via `TemplateContext`
- `_active_loader` global state still needed for `${arg:*}` resolver in config,
  but no longer used for template resolution
- Walk-up merge for `templates:` section works exactly as `var:` did before
