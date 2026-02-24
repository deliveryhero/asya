---
title: "Injector: auto-inject compositionSelector from spec.transport for AsyncActor"
priority: 2 # medium
type: task
---


## Problem

Users must currently specify both `spec.transport` and `spec.compositionSelector.matchLabels.asya.sh/transport` on every AsyncActor manifest. These are redundant: the transport field already contains the information needed to select the right Composition. Having two fields creates a silent mismatch risk.

## Solution

Extend `asya-injector` with a second `MutatingWebhookConfiguration` rule that intercepts AsyncActor CREATE/UPDATE and auto-injects `compositionSelector` when it is absent:

```go
// If spec.compositionSelector is not set, derive it from spec.transport
spec.compositionSelector = {matchLabels: {"asya.sh/transport": spec.transport}}
```

After this, users only need:
```yaml
spec:
  transport: rabbitmq
```

## Implementation

1. Add webhook rule in `deploy/helm-charts/asya-injector/` MutatingWebhookConfiguration targeting `asyncactors` resources
2. Add handler in `src/asya-injector/` that patches compositionSelector from spec.transport
3. Remove `compositionSelector` from `examples/asyas/` manifests (redundant once webhook is live)
