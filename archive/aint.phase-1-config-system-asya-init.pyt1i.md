---
title: "Phase 1: Config system + asya init"
status: merged
priority: 2
assignee: Artem Yushkovskiy
parent: n6g6h
tags:
  - worktree:.worktrees/.worktrees/asya-lab/pyt1.phase-1-config-system-asya-init
  - branch:asya-lab/pyt1.phase-1-config-system-asya-init
  - pr:295
---

## Scope

Foundation layer: config loading system and project scaffolding. No compiler,
no cluster interaction — just the config infrastructure everything else builds on.

### 1a. Config system (OmegaConf walk-up merge)

1. **Walk-up merge**: Discover `.asya/config*.yaml` files from CWD up to repo
   root (`.git/`), merge root-first using OmegaConf with `ListMergeMode.EXTEND`
2. **Filename-to-key convention**: `config.compiler.yaml` → `compiler:` key
3. **Directory-to-key convention**: `.asya/compiler/rules.yaml` → `compiler.rules`
4. **Resolvers**: `${var.*}` (native), `${arg:*}`, `${dynamic:*}`, `${env:*}` (custom)
5. **Schema validation**: Asya semantic layer validates after OmegaConf merge
6. **Duplicate detection**: List entries with same key field = error by default,
   `override: true` marker to explicitly replace parent entries
7. **Path resolution**: `./` paths resolved to absolute before merge
8. **`asya config get`**: CLI command to read merged config values

### 1b. asya init (project scaffolding)

`asya init [--template <name>]` scaffolds `.asya/` directory:

```
.asya/
├── config.yaml              # root config with var.project_root, var.image_registry
├── compiler/
│   ├── templates/
│   │   └── actor.yaml       # AsyncActor XR template with ${dynamic:*} resolvers
│   └── rules.yaml           # empty rules file with commented examples
└── manifests/               # empty, populated by asya compile
```

Behaviors:
- Adds `.env.secret` to `.gitignore`
- Sets `var.project_root: "."` (resolved to repo root)
- Prompts for `var.image_registry` (or accepts via flag)
- Idempotent: re-running preserves existing config, adds missing files
- Templates via Copier for different project types (basic, monorepo)

## References

- `.aint/aints/asya-lab/research-compiler-resolution.md` §2.3 — walk-up merge
  algorithm, merge semantics, duplicate detection, override: true
- `.aint/aints/asya-lab/rfc.md` §7 — config schema, resolver syntax, design decisions
- `.aint/aints/asya-lab/rfc.md` §5.1 — init command
- `.aint/aints/asya-lab/research-compiler-resolution.md` §2 — config file layout
