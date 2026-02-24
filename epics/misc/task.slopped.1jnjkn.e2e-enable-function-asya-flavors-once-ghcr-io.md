---
title: "E2E: Enable function-asya-flavors once ghcr.io image is public"
priority: 2 # medium
type: task
---

## Context

Crossplane Functions use their own OCI puller, NOT containerd's image store.
kind load docker-image does NOT work for Function packages - only for regular
container images that kubelet pulls via imagePullPolicy: Never.

The function-asya-flavors image (ghcr.io/deliveryhero/function-asya-flavors:0.5.1)
has been pushed to ghcr.io but is currently internal/private. Once the admins make it
publicly accessible:

## Steps

1. Set functions.flavorsEnabled: true in both e2e profiles
2. Remove the flavorsEnabled: false comments
3. Verify e2e tests pass with flavors enabled
4. Optionally: investigate setting up a local OCI registry inside Kind

## Key insight

Two separate image loading mechanisms in Kind:
- containerd image store: used by kubelet (Pod containers) - kind load works
- Crossplane OCI puller: used by Function/Provider packages - kind load does NOT work

Crossplane Functions must be pullable from an OCI registry.
