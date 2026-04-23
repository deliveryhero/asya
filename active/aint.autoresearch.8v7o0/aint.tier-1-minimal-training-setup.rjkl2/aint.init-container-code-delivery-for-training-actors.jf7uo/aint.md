---
title: Init container code delivery for training actors
status: pushed
priority: 1 # high
dependencies: [cynl0]
tags: [tier-1, autoresearch, code-delivery, init-container]
---

## Context

Training actors currently receive code only via ConfigMap, which is limited to
small scripts. For real experimentation, actors need access to full repos or
packages — without building custom Docker images in the cloud.

The workbench is running on EKS but cannot build images. We need a way to
deliver code to training actors at pod startup using init containers.

## Problem

Building Docker images in the cloud requires a registry, build infrastructure
(Kaniko/BuildKit), and slow iteration cycles. For fast experimentation in
tier 1, we need a zero-image-build code delivery path.

## Approach: Two patterns (pick per use case)

### Pattern 1: pip install from git (hack, fast)

Init container runs `pip install git+https://...@branch` to install a package
directly from a git branch into a shared volume.

```yaml
spec:
  initContainers:
    - name: install-code
      image: python:3.13-slim
      command:
        - sh
        - -c
        - pip install --target=/code git+https://${GIT_TOKEN}@github.com/org/repo.git@${GIT_BRANCH}
      env:
        - name: GIT_TOKEN
          valueFrom: { secretKeyRef: { name: git-creds, key: token } }
        - name: GIT_BRANCH
          value: "experiment/vit-v1"
      volumeMounts:
        - name: code
          mountPath: /code
  volumes:
    - name: code
      emptyDir: {}
```

Runtime container adds `/code` to `PYTHONPATH`. Handler imports from the
installed package. Works for any pip-installable repo.

**Pros**: zero infrastructure, works today (once cynl0 lands), familiar.
**Cons**: no live reload, re-deploy to pick up changes, token in env var.

### Pattern 2: git-sync init container (proper)

Uses `registry.k8s.io/git-sync/git-sync:v4` to clone a branch into a shared
volume at pod startup.

```yaml
spec:
  initContainers:
    - name: git-sync
      image: registry.k8s.io/git-sync/git-sync:v4
      args:
        - --repo=https://github.com/org/repo.git
        - --ref=${GIT_BRANCH}
        - --root=/code
        - --one-time
      env:
        - name: GITSYNC_USERNAME
          value: "x-access-token"
        - name: GITSYNC_PASSWORD
          valueFrom: { secretKeyRef: { name: git-creds, key: token } }
      volumeMounts:
        - name: code
          mountPath: /code
  volumes:
    - name: code
      emptyDir: {}
```

**Pros**: full repo available, proper git client, well-maintained upstream image.
**Cons**: clones full repo (shallow supported), slightly more YAML.

## Recommendation

Start with Pattern 2 (git-sync) as the default. Pattern 1 is useful when you
only need a single installable package and don't want the full repo.

Both patterns are init-container only (one-time at startup). For live-reload
during development, the git state proxy sidecar (cy0p1) is the right tool.

## Deliverables

1. Example AsyncActor manifest using git-sync init container
2. Example AsyncActor manifest using pip-install init container
3. Shared git-creds Secret template
4. Documentation in workbench ONBOARDING.md

## Testing

- Deploy training actor with git-sync init container, verify code accessible at `/code`
- Deploy training actor with pip-install init container, verify package importable
- Verify handler can import from `/code` via PYTHONPATH
