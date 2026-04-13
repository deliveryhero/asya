---
title: "Remove transport from XRD spec: use defaultCompositionRef instead of per-actor compositionSelector"
status: merged
priority: 2
assignee: Artem Yushkovskiy
parent: 00001
tags:
  - worktree:.worktrees/debt/wozv.remove-transport-from-xrd-spec-use-defaultcompositi-instead
  - branch:debt/wozv.remove-transport-from-xrd-spec-use-defaultcompositi-instead
  - pr:321
---

## Problem

Every AsyncActor manifest declares `spec.transport: sqs|rabbitmq|pubsub`. This is redundant — transport is a cluster-level concern (all actors share the same message bus), not a per-actor one. Every actor and every crew member repeats the same value.

Current flow:
```
AsyncActor spec.transport: sqs
  → compositionSelector.matchLabels: asya.sh/transport: sqs
    → composition-sqs selected
```

The transport field does one thing: select which Crossplane Composition to apply. The sidecar itself only reads env vars — it never sees the XRD field.

## Proposed Flow: defaultCompositionRef

Use Crossplane's built-in `defaultCompositionRef` on the XRD, set via Helm:

```yaml
# xrd-asyncactor.yaml
spec:
  defaultCompositionRef:
    name: asya-composition-{{ .Values.transport }}
```

Compositions get deterministic names (`asya-composition-sqs`, `asya-composition-rabbitmq`, etc.).

Result:
- `transport` removed from XRD `spec.properties` and `required`
- Transport becomes a Helm value on the crossplane chart
- No actor manifest mentions transport at all
- `asya-actor` and `asya-crew` charts drop transport from values/templates

## Multi-transport escape hatch

The rare case where one actor needs a different transport is handled via Crossplane's built-in `compositionRef` (exists on every XR, outside the XRD schema):

```yaml
kind: AsyncActor
spec:
  actor: my-special-actor
  # No transport field — uses cluster default
compositionRef:
  name: asya-composition-rabbitmq  # explicit override
```

## Migration Steps

1. Add `defaultCompositionRef` to XRD template (Helm-driven)
2. Give compositions deterministic `metadata.name` values
3. Remove `transport` from XRD `spec.properties` and `required`
4. Remove `transport` from `asya-actor` and `asya-crew` values/templates
5. Remove `compositionSelector` from actor/crew templates (default handles it)
6. Update all test manifests — delete `transport: sqs` lines
7. Keep `compositionSelector` labels on compositions for backward compat

## Supersedes

- PR #287 (closed unmerged) — moved region/providerConfigRef to EnvironmentConfig. Those infra fields are already removed; the remaining scope is purely the transport field itself.
- Aint [qh2y] can be closed once this lands.
