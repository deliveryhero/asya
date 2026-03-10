---
title: "Phase 3: Local CLI (compile, expose, show, status)"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/.worktrees/asya-lab/5ifn.phase-3-local-cli-compile-expose-show-status
  - branch:asya-lab/5ifn.phase-3-local-cli-compile-expose-show-status
  - pr:297
dependencies:
  - hox4
---




## Scope

All top-level (local-only) CLI commands. No cluster interaction — these work
with just Python source and `.asya/` config on disk.

### 3a. asya compile <target>

Ties config loading, flow AST parsing, and manifest stamping into one command.

**Target resolution:**

| Input | Detection | Behavior |
|-------|-----------|----------|
| `myflow.py` | File exists, `.py` extension | Compile flow from source |
| `e_commerce.validate.process` | Dotted path, no file | Compile single actor manifest |
| `order-processing` | Kebab-case name | Recompile from existing manifests |

**Naming flags** (`--flow` and `--actor`):

Both accept a single name (when unambiguous) or `<source>=<name>` mapping:

```bash
asya compile order.py                          # auto-derive all names
asya compile order.py --flow my-order-flow     # override flow name
asya compile handler.py --actor my-handler     # single actor, override name
asya compile order.py --actor validate_order=validator \
  --actor e_commerce.processing.express_handler=express  # mapping
```

Source can be function name or fully qualified name if not ambiguous.
Default names: kebab-case from function names (`order_processing` → `order-processing`).

**Behaviors:**
- Idempotent: re-running overwrites `base/`, preserves `common/` and `overlays/`
- Auto-detect `@flow` and `@actor` decorators in source
- One `@flow` per file (error if multiple without `--flow` selector)
- Output to `.asya/manifests/<name>/`
- `--plot` flag for flow diagram (DOT + PNG)

### 3b. asya expose <target>

Generates `configmap-flows.yaml` in kustomize `base/` directory (local only).

1. Accept same target types as compile (`.py` file, kebab-name)
2. Auto-compile if given `.py` file and manifests don't exist yet
3. Read compiled manifests in `base/`, find actor with
   `asya.sh/flow-role: entrypoint` label
4. Extract flow metadata: name, description (docstring), input schema (signature)
5. Generate `base/configmap-flows.yaml` with gateway tool registration
6. Update `base/kustomization.yaml` to include the new resource

**CLI flags:**

| Flag | Description |
|------|-------------|
| `--description` | Flow description (falls back to docstring) |
| `--timeout` | E2E timeout in seconds |
| `--protocol mcp\|a2a` | Protocol (default: configurable) |
| `--input-schema` | JSON Schema inline |
| `--input-schema-file` | JSON Schema from file |

- Idempotent: re-running overwrites `configmap-flows.yaml`
- `asya unexpose` removes `configmap-flows.yaml` from `base/`
- Per-context control: users add `$patch: delete` in overlay to exclude

### 3c. asya show <target> [--context ctx]

Renders effective manifests via `kustomize build`:
```bash
asya show order-processing --context stg
# kustomize build .asya/manifests/order-processing/overlays/stg/
```

- Uses `kubectl apply -k` (kustomize bundled with kubectl, no extra binary)
- `--context` selects overlay (defaults to `default_context` from config)
- Output to stdout (pipeable to `kubectl apply -f -` or `less`)

### 3d. asya status

Local source of truth — outer-join table across two data sources:

| Column | Source |
|--------|--------|
| SOURCE | `.py` files with `@flow`/`@actor` decorators |
| COMPILED | `.asya/manifests/<flow>/` YAML files |

Scans `var.project_root` for decorated functions, matches against compiled
manifests. No cluster access needed.

## Dependencies

- [hox4] Phase 2: Compiler manifest stamping

## References

- `.aint/aints/asya-lab/rfc.md` §5.1 — top-level commands, naming flags
- `.aint/aints/asya-lab/rfc.md` §5.7 — list and discovery, data sources
- `.aint/aints/asya-lab/rfc.md` §8.1.2 — gateway exposure, ConfigMap schema,
  SSA field managers, CLI flags, per-context control
- `.aint/aints/asya-lab/adr.k-d-command-split.md` — target resolution table
- `a2a-protocol-compliance-gateway/adr.configmap-flow-registry.md` — ConfigMap
  flow registry design
