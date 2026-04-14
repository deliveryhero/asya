---
title: "Implement ConfigMap-based flow registry: YAML toolstore + Helm chart + RBAC (ADR impl)"
status: merged
priority: 2
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/a2a-protocol-compliance-gateway/zaai.configmap-toolstore-adr-impl
  - branch:a2a-protocol-compliance-gateway/zaai.configmap-toolstore-adr-impl
  - pr:277
reason: "PR #277 merged"
---

Implement the accepted ADR (`adr.configmap-flow-registry.md`): replace the
PostgreSQL-backed `tools` table with a ConfigMap-mounted `flows.yaml` file,
add fsnotify hot-reload, update the Helm chart to mount the ConfigMap, and
add RBAC for data scientists to patch flows via `kubectl`.

**ADR reference**: `adr.configmap-flow-registry.md` (accepted 2026-03-06)

## 1. Gateway backend (src/asya-gateway)

### toolstore/types.go
- Add `FlowConfig` struct matching the `flows.yaml` schema (ADR §schema):
  `Name`, `Entrypoint`, `Description`, `TimeoutSec`, `MCP *MCPConfig`, `A2A *A2AConfig`
- `MCPConfig`: `InputSchema json.RawMessage`
- `A2AConfig`: `Tags`, `Examples`, `InputModes`, `OutputModes`
- Keep `Tool` as the internal runtime type; `FlowConfig` is the YAML surface
- Keep `RegisterRequest` / `A2AConfig` types for backward compat in tests (or remove if no longer needed)

### toolstore/registry.go
- Remove `pgxpool.Pool` field and all SQL queries (`Upsert`, `Refresh`)
- Replace `NewRegistry(ctx, pool)` with `NewRegistryFromDir(dir string)` —
  reads all `*.yaml` files in the mounted config directory on startup
- Add `LoadFromDir(dir string) error` — parses YAML into `[]FlowConfig`,
  maps each to `Tool`, updates `atomic.Value` cache
- Remove `Upsert()` — write path is gone (ConfigMap is kubectl-only)
- Keep `All()`, `GetByName()`, `MCPTools()`, `A2ASkills()` unchanged (same interface)

### toolstore/watcher.go (new file, ~30 LOC)
- fsnotify watcher on the mounted config directory
- Debounce 500ms for rapid kubelet write bursts (kubelet may write multiple files atomically)
- On CREATE/WRITE/REMOVE events: call `LoadFromDir()`, log reload at INFO level
- On invalid YAML: log error, keep previous valid cache (no crash, no empty serve)

### toolstore/handler.go
- Remove `handleRegister` (POST handler) — write path is kubectl now
- Keep `handleList` (GET handler) for `GET /mesh/expose` read-only visibility
- `HandleExpose` now only serves GET; return 405 Method Not Allowed on POST

### cmd/gateway/main.go
- Replace `toolstore.NewRegistry(ctx, pool)` with
  `toolstore.NewRegistryFromDir(os.Getenv("ASYA_CONFIG_PATH"))`
- Start watcher goroutine after registry init: `go watcher.Watch(ctx, configPath, registry)`

### db/sqitch
- Do NOT remove migration `009_tools_table_and_status_values` (history must be preserved)
- Add new migration `011_drop_tools_table`: `DROP TABLE IF EXISTS tools`

## 2. Helm chart (deploy/helm-charts/asya-gateway)

### values.yaml
```yaml
flowsConfig:
  mountPath: /etc/asya/flows
```

### templates/deployment.yaml
Add volume + volumeMount:
```yaml
volumes:
  - name: gateway-flows
    configMap:
      name: gateway-flows
      optional: true   # gateway starts healthy with empty skills list

volumeMounts:
  - name: gateway-flows
    mountPath: {{ .Values.flowsConfig.mountPath }}
    readOnly: true
```
Add env var:
```yaml
- name: ASYA_CONFIG_PATH
  value: {{ .Values.flowsConfig.mountPath }}
```

### templates/configmap-flows.yaml (new)
Starter empty ConfigMap deployed with the chart:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-flows
  namespace: {{ .Release.Namespace }}
  labels:
    asya.sh/component: gateway
    asya.sh/config-type: flows
data:
  flows.yaml: |
    flows: []
```

### templates/rbac-flow-exposer.yaml (new)
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: asya-flow-exposer
  namespace: {{ .Release.Namespace }}
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    resourceNames: ["gateway-flows"]
    verbs: ["get", "patch", "update"]
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: asya-flow-exposer
  namespace: {{ .Release.Namespace }}
subjects:
  - kind: Group
    name: {{ .Values.flowsConfig.exposerGroup | default "asya-flow-exposers" }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: asya-flow-exposer
```

## 3. E2E test changes (testing/e2e)

Current setup registers tools via `POST /mesh/expose` from `deploy.sh`.
After this change:
1. Create `gateway-flows` ConfigMap in Kind cluster with test flows (in `deploy.sh`)
2. Remove all `POST /mesh/expose` registration calls
3. `test_a2a_e2e.py::test_extended_agent_card_has_skills` verifies skills come from ConfigMap

## flows.yaml schema reference

```yaml
flows:
  - name: echo
    entrypoint: echo-actor
    description: "Echo the input payload"
    mcp:
      inputSchema:
        type: object
        properties:
          text: { type: string }
        required: [text]
    a2a:
      tags: [echo, test]
      examples: ["Echo hello world"]
```

## What stays unchanged

- `Registry` interface: `All()`, `GetByName()`, `MCPTools()`, `A2ASkills()`
- In-memory `atomic.Value` cache pattern
- MCP server, A2A executor, task store, queue client
- PostgreSQL for task state (`tasks` table untouched)

## Testing

- Unit: `NewRegistryFromDir` loads YAML, populates `MCPTools()` and `A2ASkills()` correctly
- Unit: malformed YAML → `LoadFromDir` returns error, previous cache preserved
- Unit: flow with neither `mcp:` nor `a2a:` → validation error
- Unit: watcher debounce: rapid writes → single `LoadFromDir` call after 500ms
- Component: gateway starts with test `flows.yaml` → Agent Card has correct skills
- Component: overwrite YAML file → reload within 1s → Agent Card updated
- E2E: `test_extended_agent_card_has_skills` passes with ConfigMap-sourced flows

## Implementation estimate

~80 LOC Go (50 YAML loader + 30 watcher) + ~30 LOC removed + ~100 LOC YAML (Helm) + test updates
