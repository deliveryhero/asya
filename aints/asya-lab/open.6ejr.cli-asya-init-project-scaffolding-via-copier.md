---
title: "CLI: asya init (project scaffolding via Copier)"
priority: 2 # medium
---

## Scope

Implement `asya init [--template <name>]` to scaffold a new `.asya/` directory.

### What it creates

```
.asya/
├── config.yaml              # root config with var.project_root, var.image_registry
├── compiler/
│   ├── templates/
│   │   └── actor.yaml       # AsyncActor XR template with ${dynamic:*} resolvers
│   └── rules.yaml           # empty rules file with commented examples
└── manifests/               # empty, populated by asya compile
```

### Behaviors

- Adds `.env.secret` to `.gitignore`
- Sets `var.project_root: "."` (resolved to repo root)
- Prompts for `var.image_registry` (or accepts via flag)
- Idempotent: re-running preserves existing config, adds missing files
- Templates via Copier for different project types (basic, monorepo)

## Dependencies

None (entry point, no other asya-lab components needed)

## References

- `.aint/aints/asya-lab/rfc.md` §5.1 — init command
- `.aint/aints/asya-lab/rfc.md` §7 — config schema, directory structure
- `.aint/aints/asya-lab/research-compiler-resolution.md` §2 — config file layout
