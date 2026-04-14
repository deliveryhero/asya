---
title: "XRD: validate secretName as DNS label (pattern constraint)"
status: open
priority: 3
dependencies:
  - wcnwl
---

## Problem

`spec.secretRefs[].secretName` was added in [wcnw] (PR #282) with only `minLength: 1`.
This accepts invalid Kubernetes Secret names like `My_Secret` or `my secret`. Without
the constraint, the AsyncActor CR is accepted by Crossplane but the actor pod fails at
admission time when the injector webhook passes the bad name to `secretKeyRef` — a
confusing error far from the root cause.

Kubernetes Secret names must be valid DNS labels (RFC 1123):
- lowercase alphanumeric and hyphens only
- must start and end with an alphanumeric character
- max 63 characters

## Scope

One field, two extra constraints in `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml`:

```yaml
# before (wcnw):
secretName:
  type: string
  description: Name of the Kubernetes Secret in the same namespace
  minLength: 1

# after (euan):
secretName:
  type: string
  description: Name of the Kubernetes Secret in the same namespace
  minLength: 1
  maxLength: 63
  pattern: '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'
```

The pattern is identical to what is already used for `spec.actor` (line 41) and
`spec.stateProxy[].name` (line 226) in the same XRD file — consistency across all
user-supplied Kubernetes resource name fields.

No Go code changes. No Crossplane composition changes. XRD schema only.

## Acceptance Criteria

- `secretName` in the XRD has `maxLength: 63` and `pattern: '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'`
- `make lint` passes (yamlfmt, yamllint)
- Helm template renders cleanly: `helm template deploy/helm-charts/asya-crossplane/ | grep -A5 secretName`

## Notes

- Depends on [wcnw] being on `main` first — the `secretRefs` block does not exist on
  `aint-sync` yet
- No unit tests needed: this is a declarative schema constraint, not code logic
- The `envVar` field in `keys[]` intentionally does NOT get a DNS label pattern —
  env var names allow uppercase and underscores (`OPENAI_API_KEY`), which are not
  valid DNS labels
