---
title: "XRD: Add stateProxy field to AsyncActor schema"
status: merged
priority: 1
dependencies:
  - 1ipgh
tags:
  - pr:195
---

Add the optional stateProxy field to the AsyncActor XRD (CompositeResourceDefinition):

stateProxy is an array of mount configurations:
- name (required): DNS-compatible unique mount identifier
- mount.path (required): absolute path inside runtime container (e.g., /state/meta)
- connector.image (required): full container image reference for the proxy
- connector.env (optional): backend-specific env vars passed to connector container
- connector.resources (optional): Kubernetes resource requests/limits

Example spec:
```yaml
spec:
  stateProxy:
    - name: meta
      mount:
        path: /state/meta
      connector:
        image: asya-bridges/state-proxy/redis-buffered-cas:latest
        env:
          - name: STATE_ENDPOINT
            value: "redis://context-store:6379/0"
```

Add OpenAPI validation: name must be DNS label, mount.path must start with /, image is required string.

Phase: 3 (Injector and XRD integration)
