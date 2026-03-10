---
title: "CLI: asya k build (image building)"
priority: 2 # medium
---

## Scope

Implement `asya k build <target>` — thin command runner for image building.

### What it does

1. Resolve target to build entries in config (module → image + command)
2. Run opaque shell `command` with variable substitution (`${.image}`, `${arg:tag}`)
3. `--push` flag appends registry push after build
4. Multi-image builds: sequential, fail-fast, `[build 1/N]` progress prefixes

### Behaviors

- Asya is a thin command runner, not a build system
- `command` is a single shell string (not nested local/remote)
- Variables: `${.image}` (sibling ref), `${arg:tag}` (CLI arg), `${var.*}` (config)
- Unresolved `${arg:*}` at build time = hard error
- No Asya-imposed image tag convention (CD concern)

### Example

```bash
asya k build order-processing --arg tag=v1.2
# [build 1/2] docker build -t ghcr.io/org/ecom:v1.2 .
# [build 2/2] docker build -t ghcr.io/org/shared:v1.2 .

asya k build order-processing --arg tag=v1.2 --push
# [build 1/2] docker build -t ghcr.io/org/ecom:v1.2 .
# [push  1/2] docker push ghcr.io/org/ecom:v1.2
# [build 2/2] ...
```

## Dependencies

- [pyt1] Config system (for build entries, var interpolation)

## References

- `.aint/aints/asya-lab/rfc.md` §11 — image building, three build paths
- `.aint/aints/asya-lab/rfc.md` §8.3 — build commands, multi-image, --push
- `.aint/aints/asya-lab/research-seamless-build.md` §7 — build command design
- `.aint/aints/asya-lab/research-compiler-resolution.md` §2 — build entry schema
