---
title: "CLI: asya compile command with --flow/--actor naming flags"
priority: 2 # medium
---

## Scope

Implement the `asya compile` CLI command that ties together config loading,
flow AST parsing, and manifest stamping into a single user-facing command.

### Target resolution

| Input | Detection | Behavior |
|-------|-----------|----------|
| `myflow.py` | File exists, `.py` extension | Compile flow from source |
| `e_commerce.validate.process` | Dotted path, no file | Compile single actor manifest |
| `order-processing` | Kebab-case name | Recompile from existing manifests |

### Naming flags

Both `--flow` and `--actor` accept a single name (when unambiguous) or a
`<source>=<name>` mapping:

```bash
asya compile order.py                          # auto-derive all names
asya compile order.py --flow my-order-flow     # override flow name
asya compile handler.py --actor my-handler     # single actor, override name
asya compile order.py --actor validate_order=validator \
  --actor e_commerce.processing.express_handler=express  # mapping
```

Source can be function name or fully qualified name if not ambiguous.

Default names: kebab-case from function names (`order_processing` -> `order-processing`).

### Behaviors

- Idempotent: re-running overwrites `base/`, preserves `common/` and `overlays/`
- Auto-detect `@flow` and `@actor` decorators in source
- One `@flow` per file (error if multiple without `--flow` selector)
- Output to `.asya/manifests/<name>/`
- `--plot` flag for flow diagram (DOT + PNG)

## Dependencies

- [pyt1] Config system
- [hox4] Manifest stamping

## References

- `.aint/aints/asya-lab/rfc.md` §5.1 — top-level commands, naming flags
- `.aint/aints/asya-lab/adr.k-d-command-split.md` — target resolution table
