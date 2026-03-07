# RFC: Asya Lens -- Self-Hosted Dashboard and IDE

**Status**: Proposed
**Date**: 2026-02-27
**Epic**: 1juy.asya-lens
**Depends on**: 1jux (asya-lab), 1juv (asya-ui)

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
|  | REST + WebSocket |                                 |
|  +--------+---------+                                 |
|            |                                          |
|  kubectl / helm / Docker (from asya-lab[deploy])      |
+------------------------------------------------------+
         |
    ASYA_CONTEXT -> target cluster / compose project
```

### 3.1 Components Inside the Image

| Component | Source | Purpose |
|---|---|---|
| code-server | `codercom/code-server` base image | Browser-based VSCode |
| Asya VSCode extension | `.vsix` from `src/asya-ui/packages/vscode/` | Editor integration, panels |
| `asya-lab[ui,deploy]` | PyPI / wheel | SDK, CLI, FastAPI server, kubectl/helm wrappers |
| kubectl | Official binary | K8s interaction |
| helm | Official binary | Chart management |
| Python 3.13+ | System package | Runtime for asya-lab |

### 3.2 Lifecycle

1. Container starts code-server on configured port (default 8443)
2. User opens browser, gets VSCode environment
3. Asya extension activates, spawns `asya serve` as subprocess
4. Extension panels (flow diagram, status, logs) are immediately available
5. `asya serve` reads ASYA_CONTEXT to determine target cluster/namespace

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
  context: k8s-prod
  readonly: true           # disable config editing
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
  context: k8s-stg
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

context:
  name: k8s-prod           # ASYA_CONTEXT value
  namespace: production     # target namespace for actor operations
  kubeconfig: ""            # empty = use in-cluster config

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

`asya-lens` is context-aware via the same mechanism as the CLI:

- `ASYA_CONTEXT` environment variable (set via Helm values)
- In-cluster kubeconfig for K8s targets
- Can target a different cluster via explicit kubeconfig mount

For multi-cluster visibility, deploy one `asya-lens` per cluster or use a
kubeconfig with multiple contexts and switch via the UI.

---

## 8. Security Considerations

- code-server supports password authentication and can be placed behind an
  ingress with SSO (OAuth2 proxy, Dex, etc.)
- Dashboard mode should use read-only RBAC to prevent accidental changes
- The container runs as non-root (code-server default)
- Secrets (kubeconfig, passwords) should be mounted from K8s secrets, not
  baked into the image

---

## 9. Build Pipeline

```
1. Build @asya/ui components (pnpm build in src/asya-ui/)
2. Build VSCode extension (.vsix) (pnpm build in src/asya-ui/packages/vscode/)
3. Build asya-lab wheel (uv build in src/asya-lab/)
4. Build asya-lens Docker image:
   - FROM codercom/code-server
   - COPY asya-vscode.vsix
   - pip install asya-lab[ui,deploy]
   - code-server --install-extension
```

Dependencies: asya-lens depends on both asya-lab (wheel) and asya-ui (vsix)
build artifacts. CI must build them in order.

---

## 10. Related Epics

| Epic | Relationship |
|---|---|
| 1jux (Asya Lab) | Python SDK packaged inside this image |
| 1juv (Asya UI) | VSCode extension and React components bundled here |
| 1jow (Client UX Design) | Parent design document |
