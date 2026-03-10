# RFC: Asya Lens -- Self-Hosted Dashboard and IDE

**Status**: Proposed (revised 2026-03-10)
**Date**: 2026-02-27 (original), 2026-03-10 (updated references)
**Epic**: asya-lens
**Depends on**: asya-lab (Python SDK + `asya serve`), asya-ui (`@asya/ui` components)

---

## 1. Summary

This RFC defines `asya-lens`, a single Docker image that serves as both a shared
status dashboard and a self-hosted development environment. Built on code-server
with the Asya VSCode extension and `asya-lab[ui,deploy]` pre-installed, it
provides a browser-based window into Asya actor meshes.

---

## 2. Image Naming

| Candidate | Verdict | Reason |
|---|---|---|
| `asya-lens` | **Chosen** | Practical: something you look through to observe; works for both dashboard and IDE modes |
| `asya-dashboard` | Rejected | Undersells the IDE capability |
| `asya-studio` | Rejected | User preference |
| `asya-console` | Rejected | Overloaded term (K8s has "console") |
| `asya-workbench` | Rejected | Generic |

---

## 3. Architecture

```
+------------------------------------------------------+
|  asya-lens container                                  |
|                                                       |
|  +------------------+                                 |
|  | code-server      |  (browser-based VSCode)         |
|  |  +-------------+ |                                 |
|  |  | Asya ext    | |  spawns asya serve on activation|
|  |  +------+------+ |                                 |
|  +---------|--------+                                 |
|            v                                          |
|  +------------------+                                 |
|  | asya serve       |  (FastAPI, from asya-lab[ui])   |
|  | REST + WS        |  K8s Python SDK for live data   |
|  +--------+---------+                                 |
|            |                                          |
|  .asya/ config (mounted or baked in)                  |
+------------------------------------------------------+
         |
    in-cluster config -> target K8s API server
```

### 3.1 Components Inside the Image

| Component | Source | Purpose |
|---|---|---|
| code-server | `codercom/code-server` base image | Browser-based VSCode |
| Asya VSCode extension | `.vsix` built from `src/asya-lab/ui/` | Editor integration, webview panels |
| `asya-lab[ui,deploy]` | PyPI / wheel | SDK, CLI, FastAPI server, `@asya/ui` SPA |
| K8s Python SDK | `kubernetes` pip package (dep of asya-lab) | Native watch API for live actor status |
| kubectl | Official binary | Fallback CLI, log streaming |
| helm | Official binary | Chart management |
| Python 3.13+ | System package | Runtime for asya-lab |

### 3.2 Lifecycle

1. Container starts code-server on configured port (default 8443)
2. User opens browser, gets VSCode environment
3. Asya extension activates, spawns `asya serve` as subprocess
4. `asya serve` discovers `.asya/` via walk-up from working directory
   (see `asya-ui/rfc.md` §4 for resolution algorithm)
5. Extension webview connects directly to `asya serve` via HTTP + WebSocket
   (no postMessage relay for data — see `asya-ui/rfc.md` §7)
6. `asya serve` uses in-cluster K8s config for live actor status
   (K8s Python SDK watch API — see `asya-ui/rfc.md` §5.2)

### 3.3 Data Flow

The webview talks directly to `asya serve` — the extension host is thin:

```
Webview (React)  --HTTP/WS-->  asya serve  --K8s SDK-->  K8s API server
     |                             |
     |                        local .asya/ files
     |                        (config, manifests, graph JSON)
     |
     +--postMessage-->  Extension Host  (only for VSCode-specific actions:
                                         open file, show notification)
```

`asya serve` provides:
- REST API for static data (config, manifests, graph JSON)
- WebSocket `/ws/actors` for live actor status (K8s watch fan-out)
- SSE for log streaming and gateway task progress
- Full API spec in `asya-ui/rfc.md` §5.2

---

## 4. Usage Modes

### 4.1 Dashboard Mode

For ops teams, wall monitors, CI dashboards. Users open the browser and
interact with the status panels without writing code.

Primary panels:
- **StatusDashboard**: overview grid of all actors (status, replicas, queue depth)
- **FlowDiagram**: interactive flow visualization with clickable nodes
- **LogViewer**: streaming aggregated logs with actor-name coloring

Configuration:
```yaml
# Helm values for dashboard mode
asya-lens:
  mode: dashboard          # optional: can hint at default panel
  readonly: true           # disable config editing, enforced by asya serve
```

### 4.2 IDE Mode

For data scientists and developers. Full code-server experience with the
Asya extension pre-installed. Users can write flows, compile, deploy, and
observe -- all from the browser.

Configuration:
```yaml
# Helm values for IDE mode
asya-lens:
  mode: ide
  persistence:
    enabled: true
    size: 10Gi             # PVC for user workspace
```

### 4.3 Same Image, Different Config

Both modes use the same Docker image. The mode is determined by Helm values
and RBAC configuration:
- Dashboard mode: read-only RBAC, no PVC, opens to status panel
- IDE mode: read-write RBAC, PVC for workspace, opens to editor

---

## 5. Docker Image

### 5.1 Dockerfile

```dockerfile
FROM codercom/code-server:latest

# Install Python and build tools
RUN sudo apt-get update && sudo apt-get install -y \
    python3 python3-pip python3-venv \
    && sudo rm -rf /var/lib/apt/lists/*

# Install kubectl and helm
RUN curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && sudo install kubectl /usr/local/bin/ \
    && curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Install asya-lab with UI and deploy extras
RUN pip install asya-lab[ui,deploy]

# Install the VSCode extension
COPY asya-vscode.vsix /tmp/
RUN code-server --install-extension /tmp/asya-vscode.vsix \
    && rm /tmp/asya-vscode.vsix

# Seed .asya/ config for in-cluster context (optional, can be mounted)
COPY .asya/ /home/coder/.asya/

EXPOSE 8443
```

### 5.2 Image Tags

```
ghcr.io/deliveryhero/asya-lens:latest
ghcr.io/deliveryhero/asya-lens:v0.1.0
ghcr.io/deliveryhero/asya-lens:<git-sha>
```

---

## 6. Helm Chart

Deployed via the `asya-lens` Helm chart in `deploy/helm-charts/asya-lens/`.

### 6.1 Key Values

```yaml
replicaCount: 1

image:
  repository: ghcr.io/deliveryhero/asya-lens
  tag: latest

auth:
  enabled: true
  password: ""              # code-server password (from secret)

persistence:
  enabled: false            # true for IDE mode
  size: 10Gi
  storageClass: ""

ingress:
  enabled: true
  host: lens.asya.internal

serviceAccount:
  create: true
  # RBAC for reading actor status, logs, etc.
  # Dashboard mode: read-only
  # IDE mode: read-write
```

### 6.2 RBAC

The service account needs permissions to:
- Read/list AsyncActor CRs, pods, deployments, configmaps
- Read pod logs
- (IDE mode) Create/update/delete AsyncActor CRs and configmaps

---

## 7. Context Awareness

`asya-lens` uses the same `.asya/` resolution as all asya tools (see
`asya-ui/rfc.md` §4):

- `.asya/config.yaml` inside the container defines contexts, transports, etc.
- In IDE mode, users may have their own `.asya/` in their workspace (PVC) —
  it takes precedence over the baked-in one (nearest-wins walk-up)
- In dashboard mode, the baked-in `.asya/` is the only one (no user workspace)
- `asya serve` uses in-cluster kubeconfig automatically when running inside K8s

For multi-cluster visibility, deploy one `asya-lens` per cluster or use a
kubeconfig with multiple contexts and switch via the UI.

---

## 8. Security Considerations

- code-server supports password authentication and can be placed behind an
  ingress with SSO (OAuth2 proxy, Dex, etc.)
- Dashboard mode should use read-only RBAC to prevent accidental changes
- `asya serve` enforces `readonly: true` at the API level — PUT/POST requests
  are rejected regardless of RBAC (defense in depth)
- The container runs as non-root (code-server default)
- Secrets (kubeconfig, passwords) should be mounted from K8s secrets, not
  baked into the image
- `asya serve` binds to `127.0.0.1` inside the container — only code-server's
  webview can reach it. External access goes through code-server's auth.

---

## 9. Build Pipeline

```
1. Build @asya/ui + widget bundle:
   cd src/asya-lab/ui && npm run build && npm run build:widget
2. Build asya-lab wheel (includes @asya/ui static assets):
   cd src/asya-lab && uv build
3. Build VSCode extension (.vsix):
   cd src/asya-lab/ui && npm run build:vscode
4. Build asya-lens Docker image:
   - FROM codercom/code-server
   - pip install asya-lab[ui,deploy]
   - COPY asya-vscode.vsix + code-server --install-extension
```

Dependencies: asya-lens depends on asya-lab (wheel, includes `@asya/ui` SPA)
and the VSCode extension (.vsix, built from `src/asya-lab/ui/`). CI builds
them in order.

---

## 10. Related Epics

| Epic | Relationship |
|---|---|
| asya-lab | Python SDK, CLI, `asya serve` backend — packaged inside this image |
| asya-ui | `@asya/ui` React components, provider pattern, graph schema — bundled here |
