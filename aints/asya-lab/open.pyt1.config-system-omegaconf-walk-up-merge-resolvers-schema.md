---
title: "Config system: OmegaConf walk-up merge, resolvers, schema validation"
priority: 2 # medium
---

## Scope

Implement the config loading foundation for asya-lab:

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

## References

- `.aint/aints/asya-lab/research-compiler-resolution.md` §2.3 — walk-up merge
  algorithm, merge semantics, duplicate detection, override: true
- `.aint/aints/asya-lab/rfc.md` §7 — config schema, resolver syntax, design decisions
