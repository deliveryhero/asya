---
title: "Phase 1: Dual-deployment gateway split"
status: merged
priority: 1
assignee: Artem Yushkovskiy
tags:
  - phase:1
  - worktree:.worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split
  - branch:agentic-security/1fuy.phase-1-dual-deployment-gateway-split
  - pr:269
---

Split gateway into two deployment modes (api + mesh) for network-level route
isolation. Wire existing A2A auth to the api mode. No new auth code.

See `rfc.md` section 7, Phase 1.

## Scope

- Add `ASYA_GATEWAY_MODE` env var (`api`, `mesh`, or `testing` for dev/all)
- Gate route registration in `main.go` based on mode; fail-fast if unset/invalid
- Update Helm chart to produce two Deployments + two Services from one release
- Update sidecar `ASYA_GATEWAY_URL` to point to mesh service name
- Update integration/e2e tests for dual-deployment topology
- Existing A2A auth (API key + JWT, merged in 7fuy) works unchanged

## Not in Scope

- New auth middleware (Phase 2+)
- MCP auth (Phase 2+)
- NetworkPolicy (optional hardening, separate task)

## Acceptance Criteria

- `ASYA_GATEWAY_MODE=api` serves only /a2a/*, /mcp/*, /.well-known/*, /tools/call, /health
- `ASYA_GATEWAY_MODE=mesh` serves only /mesh/*, /health
- `ASYA_GATEWAY_MODE=testing` serves all routes (for local dev/tests)
- Unset or invalid `ASYA_GATEWAY_MODE` → immediate startup failure (fail-fast)
- Single `helm install` produces `<release>-api` and `<release>-mesh` Deployments + Services
- Sidecar `ASYA_GATEWAY_URL` points to `<release>-mesh` service
- A2A auth (API key + JWT) applies to /a2a/* on api deployment

## Design

### Route groups

| Mode      | Routes served                                                              |
|-----------|----------------------------------------------------------------------------|
| `api`     | `/a2a/*`, `/mcp`, `/mcp/sse`, `/.well-known/*`, `/tools/call`, `/health`  |
| `mesh`    | `/mesh/*`, `/mesh/expose`, `/health`                                       |
| `testing` | all of the above (for component/integration tests)                         |

### main.go structure

`ASYA_GATEWAY_MODE` is required. Missing/invalid → `slog.Error` + `os.Exit(1)`.

Route registration extracted into two functions:
- `registerAPIRoutes(mux, taskHandler, mcpServer, a2aHandler, cardProducer, apiKey)`
- `registerMeshRoutes(mux, taskHandler, registry, apiKey)`

Switch via `buildRoutes(mux, mode, ...)`:
```go
switch mode {
case "api":
    registerAPIRoutes(mux, ...)
case "mesh":
    registerMeshRoutes(mux, ...)
case "testing":
    registerAPIRoutes(mux, ...)
    registerMeshRoutes(mux, ...)
default:
    return fmt.Errorf("ASYA_GATEWAY_MODE must be set to api|mesh|testing, got: %q", mode)
}
mux.HandleFunc("/health", ...)
```

### Helm chart naming

Single `helm install asya-gateway` creates:

| Resource   | Name             | Mode env var               |
|------------|------------------|----------------------------|
| Deployment | `<fullname>-api` | `ASYA_GATEWAY_MODE=api`    |
| Deployment | `<fullname>-mesh`| `ASYA_GATEWAY_MODE=mesh`   |
| Service    | `<fullname>-api` | —                          |
| Service    | `<fullname>-mesh`| —                          |

Shared ConfigMap (`<fullname>`) holds transport + DB config.
Each Deployment injects its own `ASYA_GATEWAY_MODE` inline (not from ConfigMap).
Selector labels: `app.kubernetes.io/component: api|mesh`.
Mesh service is always ClusterIP.

### Test changes

- **Component/integration tests**: add `ASYA_GATEWAY_MODE=testing` to gateway service env
  in Docker Compose profiles and `.env.tester`
- **E2E profiles**: `ASYA_GATEWAY_URL` updated to `<release>-mesh.<ns>.svc.cluster.local:8080`;
  injector `gatewayURL` updated to mesh service name

---

# Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split asya-gateway into two deployment units (api + mesh) via a required env var, with fail-fast for missing/invalid mode, producing two Deployments + Services from one Helm release.

**Architecture:** Same binary, mode-gated route registration via `ASYA_GATEWAY_MODE`. Helm templates split into api/mesh variants sharing one ConfigMap. Tests use `testing` mode (all routes on one service).

**Tech Stack:** Go 1.24, net/http ServeMux, Helm 3, Docker Compose, pytest

---

### Task 1: Extract route registration and add mode validation in main.go

**Files:**
- Modify: `src/asya-gateway/cmd/gateway/main.go`
- Create: `src/asya-gateway/cmd/gateway/main_test.go`

**Step 1: Write the failing tests**

Create `src/asya-gateway/cmd/gateway/main_test.go`:

```go
package main

import (
    "net/http"
    "testing"
    "github.com/stretchr/testify/require"
)

func TestBuildRoutes_MissingMode(t *testing.T) {
    mux := http.NewServeMux()
    err := buildRoutes(mux, "", nil, nil, nil, nil, "")
    require.Error(t, err)
    require.Contains(t, err.Error(), "ASYA_GATEWAY_MODE")
}

func TestBuildRoutes_UnknownMode(t *testing.T) {
    mux := http.NewServeMux()
    err := buildRoutes(mux, "production", nil, nil, nil, nil, "")
    require.Error(t, err)
}

func TestBuildRoutes_APIMode(t *testing.T) {
    mux := http.NewServeMux()
    err := buildRoutes(mux, "api", nil, nil, nil, nil, "")
    require.NoError(t, err)
}

func TestBuildRoutes_MeshMode(t *testing.T) {
    mux := http.NewServeMux()
    err := buildRoutes(mux, "mesh", nil, nil, nil, nil, "")
    require.NoError(t, err)
}

func TestBuildRoutes_TestingMode(t *testing.T) {
    mux := http.NewServeMux()
    err := buildRoutes(mux, "testing", nil, nil, nil, nil, "")
    require.NoError(t, err)
}
```

**Step 2: Run to confirm compile failure**

```bash
make -C src/asya-gateway test-unit 2>&1 | head -20
```
Expected: compile error — `buildRoutes undefined`

**Step 3: Refactor main.go**

In `src/asya-gateway/cmd/gateway/main.go`:

1. Add `registerAPIRoutes` extracting `/mcp`, `/mcp/sse`, `/tools/call`, `/a2a/`, `/.well-known/agent.json`:
```go
func registerAPIRoutes(mux *http.ServeMux, taskHandler *mcp.Handler, mcpServer *mcp.Server,
    a2aHandler http.Handler, cardProducer *a2a.CardProducer, apiKey string) {
    mux.Handle("/mcp", mcpserver.NewStreamableHTTPServer(mcpServer.GetMCPServer()))
    mux.Handle("/mcp/sse", mcpserver.NewSSEServer(mcpServer.GetMCPServer()))
    mux.HandleFunc("/tools/call", taskHandler.HandleToolCall)
    mux.Handle("/a2a/", a2aHandler)
    mux.Handle("/.well-known/agent.json", a2asrv.NewAgentCardHandler(cardProducer))
}
```

2. Add `registerMeshRoutes` extracting `/mesh/expose`, `/mesh/`, `/mesh`:
```go
func registerMeshRoutes(mux *http.ServeMux, taskHandler *mcp.Handler,
    registry *toolstore.Registry, apiKey string) {
    exposeHandler := toolstore.NewHandler(registry)
    var exposeHTTPHandler http.Handler = http.HandlerFunc(exposeHandler.HandleExpose)
    if apiKey != "" {
        exposeHTTPHandler = a2a.APIKeyMiddleware(apiKey)(exposeHTTPHandler)
    }
    mux.Handle("/mesh/expose", exposeHTTPHandler)
    mux.HandleFunc("/mesh/", func(w http.ResponseWriter, r *http.Request) {
        // ... same dispatch logic as before
    })
    mux.HandleFunc("/mesh", taskHandler.HandleMeshCreate)
}
```

3. Add `buildRoutes`:
```go
func buildRoutes(mux *http.ServeMux, mode string, taskHandler *mcp.Handler,
    mcpServer *mcp.Server, a2aHandler http.Handler, registry *toolstore.Registry,
    apiKey string) error {
    switch mode {
    case "api":
        // cardProducer constructed inside registerAPIRoutes or passed in
        registerAPIRoutes(mux, taskHandler, mcpServer, a2aHandler, nil, apiKey)
    case "mesh":
        registerMeshRoutes(mux, taskHandler, registry, apiKey)
    case "testing":
        registerAPIRoutes(mux, taskHandler, mcpServer, a2aHandler, nil, apiKey)
        registerMeshRoutes(mux, taskHandler, registry, apiKey)
    default:
        return fmt.Errorf("ASYA_GATEWAY_MODE must be set to api|mesh|testing, got: %q", mode)
    }
    mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(http.StatusOK)
        _, _ = fmt.Fprintln(w, "OK")
    })
    return nil
}
```

4. In `main()`, replace the route block with:
```go
mode := os.Getenv("ASYA_GATEWAY_MODE")
if err := buildRoutes(mux, mode, taskHandler, mcpServer, a2aHTTPHandler, registry, apiKey); err != nil {
    slog.Error("Invalid gateway mode", "error", err)
    os.Exit(1)
}
slog.Info("Gateway mode", "mode", mode)
```

Note: `cardProducer` is only needed in `api`/`testing` mode — construct it inside `registerAPIRoutes` or pass it into `buildRoutes` and forward to `registerAPIRoutes`.

**Step 4: Run unit tests**

```bash
make -C src/asya-gateway test-unit
```
Expected: all pass

**Step 5: Verify build**

```bash
make build-go 2>&1 | tail -5
```
Expected: no errors

**Step 6: Commit**

```bash
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  add src/asya-gateway/cmd/gateway/
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  commit -m "feat(gateway): add ASYA_GATEWAY_MODE with api/mesh/testing modes [1fuy]"
```

---

### Task 2: Add ASYA_GATEWAY_MODE=testing to all test gateway service definitions

**Files:**
- Modify: `testing/component/gateway/profiles/sqs.yml`
- Modify: `testing/component/gateway/profiles/rabbitmq.yml`
- Modify: `testing/shared/compose/envs/.env.tester`

**Step 1: Add env var to component test gateway service**

In both `testing/component/gateway/profiles/sqs.yml` and `rabbitmq.yml`, in the `gateway` service `environment:` block add:
```yaml
      ASYA_GATEWAY_MODE: testing
```

**Step 2: Add to shared tester env**

In `testing/shared/compose/envs/.env.tester` add:
```
ASYA_GATEWAY_MODE=testing
```

**Step 3: Run component tests**

```bash
make test-component 2>&1 | tail -20
```
Expected: all pass

**Step 4: Run integration tests**

```bash
make test-integration 2>&1 | tail -20
```
Expected: all pass

**Step 5: Commit**

```bash
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  add testing/component/gateway/profiles/ testing/shared/compose/envs/.env.tester
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  commit -m "feat(tests): set ASYA_GATEWAY_MODE=testing in gateway test configs [1fuy]"
```

---

### Task 3: Add api/mesh naming helpers to Helm _helpers.tpl

**Files:**
- Modify: `deploy/helm-charts/asya-gateway/templates/_helpers.tpl`

**Step 1: Append helpers**

Add at end of `_helpers.tpl`:

```yaml
{{/*
Fully qualified name for the api deployment/service.
*/}}
{{- define "asya-gateway.api.fullname" -}}
{{- printf "%s-api" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified name for the mesh deployment/service.
*/}}
{{- define "asya-gateway.mesh.fullname" -}}
{{- printf "%s-mesh" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Selector labels for the api deployment.
*/}}
{{- define "asya-gateway.api.selectorLabels" -}}
{{ include "asya-gateway.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
Selector labels for the mesh deployment.
*/}}
{{- define "asya-gateway.mesh.selectorLabels" -}}
{{ include "asya-gateway.selectorLabels" . }}
app.kubernetes.io/component: mesh
{{- end }}
```

**Step 2: Lint**

```bash
helm lint deploy/helm-charts/asya-gateway/ --set transports.sqs.enabled=true
```
Expected: no errors

**Step 3: Commit**

```bash
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  add deploy/helm-charts/asya-gateway/templates/_helpers.tpl
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  commit -m "feat(helm/gateway): add api/mesh naming helpers [1fuy]"
```

---

### Task 4: Split deployment.yaml into deployment-api.yaml + deployment-mesh.yaml

**Files:**
- Delete: `deploy/helm-charts/asya-gateway/templates/deployment.yaml`
- Create: `deploy/helm-charts/asya-gateway/templates/deployment-api.yaml`
- Create: `deploy/helm-charts/asya-gateway/templates/deployment-mesh.yaml`

**Step 1: Create deployment-api.yaml**

Copy `deployment.yaml` → `deployment-api.yaml`. Apply these changes:
- `metadata.name` → `{{ include "asya-gateway.api.fullname" . }}`
- `spec.selector.matchLabels` → `{{- include "asya-gateway.api.selectorLabels" . | nindent 6 }}`
- `spec.template.metadata.labels` → `{{- include "asya-gateway.api.selectorLabels" . | nindent 8 }}` (plus podLabels)
- Add to container `env:` (before `ASYA_DATABASE_URL`):
  ```yaml
        - name: ASYA_GATEWAY_MODE
          value: "api"
  ```
- Keep the DB schema init container (api mode uses DB for task tracking + tool registry)

**Step 2: Create deployment-mesh.yaml**

Copy `deployment-api.yaml` → `deployment-mesh.yaml`. Apply:
- `metadata.name` → `{{ include "asya-gateway.mesh.fullname" . }}`
- Selector labels → `asya-gateway.mesh.selectorLabels`
- `ASYA_GATEWAY_MODE` value → `"mesh"`
- Keep DB init container (mesh writes task progress to DB)

**Step 3: Remove old deployment.yaml**

```bash
rm deploy/helm-charts/asya-gateway/templates/deployment.yaml
```

**Step 4: Verify two deployments render**

```bash
helm template asya-gateway deploy/helm-charts/asya-gateway/ \
  --set transports.sqs.enabled=true | grep -E "^kind:|^  name:" | head -20
```
Expected output includes:
```
kind: Deployment
  name: asya-gateway-api
kind: Deployment
  name: asya-gateway-mesh
```

**Step 5: Lint**

```bash
helm lint deploy/helm-charts/asya-gateway/ --set transports.sqs.enabled=true
```
Expected: no errors

**Step 6: Commit**

```bash
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  add deploy/helm-charts/asya-gateway/templates/
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  commit -m "feat(helm/gateway): split into api and mesh deployments [1fuy]"
```

---

### Task 5: Split service.yaml into service-api.yaml + service-mesh.yaml

**Files:**
- Delete: `deploy/helm-charts/asya-gateway/templates/service.yaml`
- Create: `deploy/helm-charts/asya-gateway/templates/service-api.yaml`
- Create: `deploy/helm-charts/asya-gateway/templates/service-mesh.yaml`

**Step 1: Create service-api.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "asya-gateway.api.fullname" . }}
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: api
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
      {{- if and .Values.service.nodePort (eq .Values.service.type "NodePort") }}
      nodePort: {{ .Values.service.nodePort }}
      {{- end }}
  selector:
    {{- include "asya-gateway.api.selectorLabels" . | nindent 4 }}
```

**Step 2: Create service-mesh.yaml**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "asya-gateway.mesh.fullname" . }}
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: mesh
spec:
  type: ClusterIP
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    {{- include "asya-gateway.mesh.selectorLabels" . | nindent 4 }}
```

Note: mesh is always ClusterIP — not configurable, not exposed externally.

**Step 3: Remove old service.yaml**

```bash
rm deploy/helm-charts/asya-gateway/templates/service.yaml
```

**Step 4: Verify two services render**

```bash
helm template asya-gateway deploy/helm-charts/asya-gateway/ \
  --set transports.sqs.enabled=true | grep -E "^kind:|^  name:" | head -20
```
Expected: two `Service` resources named `asya-gateway-api` and `asya-gateway-mesh`.

**Step 5: Lint**

```bash
helm lint deploy/helm-charts/asya-gateway/ --set transports.sqs.enabled=true
```

**Step 6: Commit**

```bash
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  add deploy/helm-charts/asya-gateway/templates/
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  commit -m "feat(helm/gateway): split into api and mesh services [1fuy]"
```

---

### Task 6: Update e2e profiles to use mesh service name

**Files:**
- Modify: `testing/e2e/profiles/sqs-s3.yaml`
- Modify: `testing/e2e/profiles/rabbitmq-minio.yaml`
- Modify: `testing/e2e/profiles/pubsub-gcs.yaml`

**Step 1: Update ASYA_GATEWAY_URL in all profiles**

In all three files, replace every occurrence of:
```yaml
ASYA_GATEWAY_URL: "http://asya-gateway.asya-e2e.svc.cluster.local:8080"
```
with:
```yaml
ASYA_GATEWAY_URL: "http://asya-gateway-mesh.asya-e2e.svc.cluster.local:8080"
```

**Step 2: Update injector gatewayURL in all profiles**

Replace:
```yaml
    gatewayURL: http://asya-gateway.asya-e2e.svc.cluster.local:8080
```
with:
```yaml
    gatewayURL: http://asya-gateway-mesh.asya-e2e.svc.cluster.local:8080
```

**Step 3: Verify no stale bare references**

```bash
grep -rn "asya-gateway\." testing/e2e/ --include="*.yaml" | grep -v "asya-gateway-mesh\|asya-gateway-api"
```
Expected: no output

**Step 4: Commit**

```bash
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  add testing/e2e/profiles/
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  commit -m "feat(e2e): update ASYA_GATEWAY_URL to mesh service name [1fuy]"
```

---

### Task 7: Final verification — unit + lint + component + integration tests

**Step 1: Unit tests**

```bash
make test-unit
```
Expected: all pass

**Step 2: Lint**

```bash
make lint
```
Expected: no errors (auto-fix applied, no residual failures)

**Step 3: Component tests**

```bash
make test-component
```
Expected: all pass

**Step 4: Integration tests**

```bash
make test-integration
```
Expected: all pass

**Step 5: Push branch**

```bash
git -C .worktrees/agentic-security/1fuy.phase-1-dual-deployment-gateway-split \
  push -u origin HEAD
```
