---
title: Git state proxy sidecar
status: open
priority: 1 # high
tags: [autoresearch, state-proxy, git]
---

## Context

Multiple autoresearch components need git-backed filesystem access:
- Orchestrator reads/writes code on feature branches
- x-deploy reads manifests from git to deploy actors
- Actors read/write experiment tracking files on `aint-sync` branch

Today these require git credentials in the actor pod. The git state proxy
sidecar handles auth and translates file I/O to git operations.

## Design

**Base git state proxy**: mounts any git branch as a filesystem. Write = commit
+ push. Read = serve from local clone.

**Git-aint specialization**: same proxy, but with a pre-commit git hook
configured to run `git aint auto-state` (regenerates `auto_state.md`). This
is a configuration difference, not a code difference.

### Sidecar Internals

- Container has git installed (+ git-aint CLI for aint mode)
- On startup: shallow clone of configured branch into local working dir
- Read operations: serve from local clone (fast, no network)
- Write operations: write to local clone, commit + push
  - In aint mode: runs `git aint sync` instead (pull + auto_state.md + commit + push)
- Periodic pull (configurable, default 30s) to pick up remote changes
- List/stat: from local clone

### Actor Interaction

```python
# read code from feature branch
model_code = open("/code/src/train.py").read()

# write new code (git proxy commits + pushes)
with open("/code/src/train.py", "w") as f:
    f.write(new_code)

# read experiment aint (aint mode)
spec = open("/aint/active/aint.train-resnet.ab12c.md").read()
```

### StateProxyConnector Interface

- `read(key)`: read from local clone
- `write(key, data)`: write to local clone + commit + push (or `git aint sync`)
- `list(prefix, delimiter)`: listdir on local clone
- `stat(key)`: stat on local clone
- `delete(key)`: delete from local clone + commit + push

### Configuration

```yaml
stateProxy:
  # General git proxy (code access)
  - name: code
    mount:
      path: /code
    connector:
      image: asya/git-proxy:latest
      env:
        - name: GIT_REPO_URL
          valueFrom: { secretKeyRef: { name: git-creds, key: repo-url } }
        - name: GIT_TOKEN
          valueFrom: { secretKeyRef: { name: git-creds, key: token } }
        - name: GIT_BRANCH
          value: "experiment/resnet-v3"
        - name: GIT_MODE
          value: "read-write"   # or "read-only"

  # Git-aint specialization (experiment tracking)
  - name: aint
    mount:
      path: /aint
    connector:
      image: asya/git-proxy:latest
      env:
        - name: GIT_REPO_URL
          valueFrom: { secretKeyRef: { name: git-creds, key: repo-url } }
        - name: GIT_TOKEN
          valueFrom: { secretKeyRef: { name: git-creds, key: token } }
        - name: GIT_BRANCH
          value: "aint-sync"
        - name: GIT_AINT_MODE
          value: "true"         # enables git aint sync on write
```

Same image, different env vars. One implementation, two use cases.

## Implementation

Language: Python. Reuses existing `StateProxyConnector` ABC + `run_connector()`
server. `git` operations via subprocess. `git-aint` CLI installed conditionally
(only when `GIT_AINT_MODE=true`).

## Testing

- Unit: read/write/list/stat against a local git repo (mock git remote)
- Unit: aint mode triggers `git aint sync` instead of plain commit+push
- Component: full roundtrip — write file via proxy, verify git push
- Component: read-only mode rejects writes
- Component: concurrent reads during sync don't block
- Component: periodic pull picks up remote changes
