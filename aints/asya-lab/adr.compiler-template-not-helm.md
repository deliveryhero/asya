# ADR: Compiler output template is not reinventing Helm

**Status**: Accepted
**Date**: 2026-03-08
**Context**: Design of `.asya/template.yaml` output template
(research-compiler-resolution.md, section 3.8)

## Decision

The compiler uses a standalone YAML template (`.asya/template.yaml`) with
`${dynamic:*}` OmegaConf resolvers to generate output (manifests, helm values,
kustomize patches). This is printf-level substitution, not a template engine.

## Why This Is NOT Reinventing Helm

| Helm | This |
|------|------|
| `{{ if .Values.gpu }}` | No conditionals |
| `{{ range .Values.env }}` | No loops |
| `{{ include "helper" . }}` | No includes |
| 100+ sprig functions | Zero functions |
| Arbitrary Go template expressions | Fixed set of `dynamic:*` values |

The compiler has these values to place:

- `${dynamic:actor}` — actor name (derived from handler, kebab-cased)
- `${dynamic:image}` — resolved OCI image reference
- `${dynamic:handler}` — fully qualified Python handler path
- `${dynamic:flow_role}` — role within flow (entrypoint, router, processor)
- `${dynamic:timeout}`, `${dynamic:retry_*}` — extracted resiliency config
- `${dynamic:env}` — all extracted environment variables
- `${var.*}` — user constants from config.yaml
- `${arg:*}` — deploy-time parameters (tag, etc.)

No control flow, no functions, no includes. The template is static YAML with
holes punched for compiler-inferred values. OmegaConf resolves the holes —
the same mechanism used everywhere else in `.asya/*.yaml`.

## Alternatives Considered

### Use Helm directly (generate Chart + templates)

Rejected. Asya would need to maintain Go template syntax, understand Helm's
rendering pipeline, and ship a Helm dependency. The compiler knows ~5 values —
generating a full Helm chart for printf is over-engineering.

### Use Jinja2

Rejected. Jinja syntax (`{{ name }}`) is visually confusing when mixed with
OmegaConf interpolation (`${var.image_registry}`). Two different substitution
systems in the same file — unclear which engine resolves what. OmegaConf
custom resolvers (`${dynamic:actor}`) use the same syntax as everything else.

### Use `@` markers (`@name`, `@image`)

Rejected. Introduces a third syntax alongside OmegaConf `${...}` and YAML.
Custom parsing needed. OmegaConf resolvers are native — no custom parser.

## Consequences

- Template expressiveness is intentionally limited to substitution
- Complex deployment logic (GPU conditionals, environment-specific config)
  belongs in overlays or helm/kustomize — not in the compiler template
- If a team needs conditionals in their output, they use `compile.mode: helm`
  and let Helm handle it — Asya generates values.yaml, Helm renders templates
