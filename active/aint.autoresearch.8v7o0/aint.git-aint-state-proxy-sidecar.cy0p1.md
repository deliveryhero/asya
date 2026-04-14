---
title: Git-aint state proxy sidecar
status: open
priority: 1 # high
tags: [autoresearch, state-proxy, git-aint]
---

## Context

Autoresearch orchestrator actors need to read/write experiment tracking files
(aints) during execution. Today git-aint operates as a CLI tool requiring git
access. Actors shouldn't deal with git auth — the state proxy sidecar handles it.

## Design

Mount path: `/aint/` in actor container.

Sidecar internals:
- Container has git + git-aint CLI installed
- On startup: shallow clone of `aint-sync` branch into local working dir
- Read operations: serve from local clone (fast, no network)
- Write operations: write to local clone, then run `git aint sync`
  (pull + auto_state.md regen + commit + push)
- List/stat: from local clone

Actor sees:
```python
# read experiment status
spec = open("/aint/active/aint.train-resnet.ab12c.md").read()

# update experiment status
with open("/aint/active/aint.train-resnet.ab12c.md", "w") as f:
    f.write(updated_content)
# sidecar runs `git aint sync` after write
```

Implements `StateProxyConnector` interface:
- `read(key)`: read from local clone
- `write(key, data)`: write to local clone + `git aint sync`
- `list(prefix, delimiter)`: listdir on local clone
- `stat(key)`: stat on local clone
- `delete(key)`: delete from local clone + `git aint sync`

Config in AsyncActor manifest:
```yaml
stateProxy:
  - name: aint
    mount:
      path: /aint
    connector:
      image: asya/aint-proxy:latest
      env:
        - name: GIT_REPO_URL
          valueFrom: { secretKeyRef: { name: git-creds, key: repo-url } }
        - name: GIT_TOKEN
          valueFrom: { secretKeyRef: { name: git-creds, key: token } }
```

## Implementation

Language: Python (git-aint is a bash/Python tool, connector interface is Python).
Reuses existing `StateProxyConnector` ABC + `run_connector()` server.

## Testing

- Unit: read/write/list/stat against a local git repo (mock git remote)
- Component: full roundtrip — write aint file via state proxy, verify git push
- Component: concurrent reads during sync don't block
