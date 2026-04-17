# PR4: Helm Chart + Ingress + E2E + Docs — Execution Plan

Final integration PR. Depends on PR1 (mesh-api + state-proxy-pg), PR2 (adapters),
PR3 (sidecar changes). Brings everything together: multi-container Deployment,
Services, Ingress, ConfigMaps, Crossplane env var removal, E2E tests, documentation.

## Table of Contents

1. [Helm Chart Overhaul](#1-helm-chart-overhaul)
2. [nginx Ingress Templates](#2-nginx-ingress-templates)
3. [Crossplane Composition Changes](#3-crossplane-composition-changes)
4. [E2E Test Infrastructure](#4-e2e-test-infrastructure)
5. [E2E Test Scenarios](#5-e2e-test-scenarios)
6. [Documentation](#6-documentation)
7. [Migration and Backward Compatibility](#7-migration-and-backward-compatibility)
8. [Cascade Checklist](#8-cascade-checklist)

---

## 1. Helm Chart Overhaul

### 1.1 values.yaml — Full Replacement

Replace `deploy/helm-charts/asya-gateway/values.yaml` entirely. The current
values.yaml has a monolithic gateway binary with api/mesh split. The new one has
multi-container pod with mesh-api + optional adapters + state-proxy sidecars.

```yaml
replicaCount: 1

# --- Container images ---
meshApi:
  image:
    repository: ghcr.io/deliveryhero/asya-mesh-api
    tag: ""  # defaults to Chart.AppVersion
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: 250m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi

mcp:
  enabled: false
  image:
    repository: ghcr.io/deliveryhero/asya-mcp-adapter
    tag: ""
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 250m
      memory: 256Mi

a2a:
  enabled: false
  image:
    repository: ghcr.io/deliveryhero/asya-a2a-adapter
    tag: ""
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 250m
      memory: 256Mi

# --- State proxy sidecars ---
stateProxy:
  mesh:
    # PG connector for envelope metadata (always present)
    type: pg
    image:
      repository: ghcr.io/deliveryhero/asya-state-proxy-pg
      tag: ""
      pullPolicy: IfNotPresent
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
    # Socket path for mesh-api <-> state-proxy communication
    socketDir: /var/run/asya-state-proxy-mesh
    # Expression indexes created on startup (comma-separated)
    indexes: "status, (deadline_at)::timestamptz"
  envelopes:
    # S3 connector for full envelopes/history (optional, for A2A history)
    enabled: false
    type: s3
    image:
      repository: ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww
      tag: ""
      pullPolicy: IfNotPresent
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
    socketDir: /var/run/asya-state-proxy-envelopes
    config:
      bucket: ""
      region: us-east-1
      endpoint: ""

# --- Database (for state-proxy-pg) ---
database:
  host: ""
  port: 5432
  name: asya_gateway
  username: asya
  password: ""
  existingSecret: ""
  existingSecretKey: password
  sslMode: disable

# --- Transport (mesh-api needs queue publish) ---
transports:
  rabbitmq:
    enabled: false
    config:
      url: "amqp://guest:guest@rabbitmq:5672/"
      exchange: "asya"
      poolSize: 20
  sqs:
    enabled: false
    config:
      endpoint: ""
      region: "us-east-1"
      visibilityTimeout: 300
      waitTimeSeconds: 20
  pubsub:
    enabled: false
    config:
      projectId: ""
      endpoint: ""

# --- Ingress ---
ingress:
  enabled: false
  className: nginx
  # External host for client-facing Ingress
  host: ""
  # Internal host for sidecar callbacks
  internalHost: ""
  annotations: {}
  tls: []
  internalAnnotations: {}

# --- Services ---
service:
  type: ClusterIP
  # External mesh-api service (port 8080)
  meshApi:
    port: 8080
  # Internal mesh-api service (port 8081, sidecar callbacks)
  meshApiInternal:
    port: 8081
    type: ClusterIP
  # MCP adapter service
  mcp:
    port: 8082
  # A2A adapter service
  a2a:
    port: 8083

# --- MCP tool definitions (mounted as ConfigMap) ---
mcpTools: []
# - name: train_model
#   description: "Train a model with given hyperparameters"
#   actor: start-my-flow
#   timeout: 3600
#   inputSchema:
#     type: object
#     properties:
#       lr: {type: number}
#     required: [lr]
#   progress: true

# --- A2A agent definitions (mounted as ConfigMap) ---
a2aAgents: []
# - name: autoresearch
#   description: "Autonomous ML experimentation agent"
#   actor: start-autoresearch
#   timeout: 14400
#   streaming: true
#   skills:
#     - id: experiment
#       name: Run experiment
#       description: "Execute training experiments"
#   inputModes: [text/plain, application/json]
#   outputModes: [text/plain, application/json]

# --- Pod configuration ---
imagePullSecrets: []
nameOverride: ""
fullnameOverride: ""

serviceAccount:
  create: true
  automount: true
  annotations: {}
  name: ""

podAnnotations: {}
podLabels: {}

podSecurityContext:
  fsGroup: 2000

securityContext:
  capabilities:
    drop:
    - ALL
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1000

autoscaling:
  enabled: false
  minReplicaCount: 1
  maxReplicaCount: 10
  targetCPUUtilizationPercentage: 80

podDisruptionBudget:
  enabled: false
  maxUnavailable: 1

nodeSelector: {}
tolerations: []
affinity: {}

# --- Tracing ---
tracing:
  endpoint: ""

# --- Helm test configuration ---
tests:
  image: alpine/k8s:1.28.3
  imagePullPolicy: IfNotPresent
```

Key changes from current values.yaml:
- Removed: `config.port`, `migration.*`, `postgresql.*`, `externalDatabase.*`,
  `exposedFlows`, `flowConfigMaps`, `flowsExposerGroup`, single `image.*`
- Added: `meshApi.*`, `mcp.*`, `a2a.*`, `stateProxy.*`, `database.*`,
  `mcpTools`, `a2aAgents`, `podDisruptionBudget.*`, `ingress.internalHost`
- Restructured: `service.*` now has per-component ports, `ingress.*` has
  external + internal

### 1.2 _helpers.tpl — New Helpers

Replace `deploy/helm-charts/asya-gateway/templates/_helpers.tpl`. Keep existing
helpers (`asya-gateway.name`, `asya-gateway.fullname`, `asya-gateway.chart`,
`asya-gateway.labels`, `asya-gateway.selectorLabels`,
`asya-gateway.serviceAccountName`, `asya-gateway.validateTransports`).

Remove:
- `asya-gateway.api.fullname` (old api deployment)
- `asya-gateway.mesh.fullname` (old mesh deployment)
- `asya-gateway.api.selectorLabels` (old)
- `asya-gateway.mesh.selectorLabels` (old)
- `asya-gateway.databaseHost` (replaced by direct values)
- `asya-gateway.databasePort` (replaced)
- `asya-gateway.databaseName` (replaced)
- `asya-gateway.databaseUsername` (replaced)
- `asya-gateway.databaseSecretName` (replaced)
- `asya-gateway.databasePasswordKey` (replaced)

Add:
```
{{- define "asya-gateway.meshApi.fullname" -}}
{{- printf "%s-mesh-api" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "asya-gateway.meshApiInt.fullname" -}}
{{- printf "%s-mesh-api-int" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "asya-gateway.mcp.fullname" -}}
{{- printf "%s-mcp" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "asya-gateway.a2a.fullname" -}}
{{- printf "%s-a2a" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Database URL constructed from database.* values.
Used by state-proxy-pg sidecar.
*/}}
{{- define "asya-gateway.databaseURL" -}}
{{- if .Values.database.host -}}
postgresql://{{ .Values.database.username }}:$(DB_PASSWORD)@{{ .Values.database.host }}:{{ .Values.database.port }}/{{ .Values.database.name }}?sslmode={{ .Values.database.sslMode }}
{{- end -}}
{{- end }}

{{/*
Internal mesh-api service URL (for x-asya-gateway-url header).
Sidecar callbacks use this URL via the envelope header.
*/}}
{{- define "asya-gateway.internalURL" -}}
http://{{ include "asya-gateway.meshApiInt.fullname" . }}.{{ .Release.Namespace }}.svc.cluster.local:{{ .Values.service.meshApiInternal.port }}
{{- end }}
```

### 1.3 deployment.yaml — Single Multi-Container Deployment

Delete both `deployment-api.yaml` and `deployment-mesh.yaml`. Create a single
`deployment.yaml`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "asya-gateway.fullname" . }}
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "asya-gateway.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
        {{- if .Values.mcp.enabled }}
        checksum/mcp-tools: {{ include (print $.Template.BasePath "/configmap-mcp-tools.yaml") . | sha256sum }}
        {{- end }}
        {{- if .Values.a2a.enabled }}
        checksum/a2a-agents: {{ include (print $.Template.BasePath "/configmap-a2a-agents.yaml") . | sha256sum }}
        {{- end }}
        {{- with .Values.podAnnotations }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      labels:
        {{- include "asya-gateway.selectorLabels" . | nindent 8 }}
        {{- with .Values.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
    spec:
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      serviceAccountName: {{ include "asya-gateway.serviceAccountName" . }}
      securityContext:
        {{- toYaml .Values.podSecurityContext | nindent 8 }}
      {{- include "asya-gateway.validateTransports" . }}
      terminationGracePeriodSeconds: 35
      containers:
      # --- mesh-api: core HTTP server ---
      - name: mesh-api
        securityContext:
          {{- toYaml .Values.securityContext | nindent 12 }}
        image: "{{ .Values.meshApi.image.repository }}:{{ .Values.meshApi.image.tag | default .Chart.AppVersion }}"
        imagePullPolicy: {{ .Values.meshApi.image.pullPolicy }}
        ports:
        - name: mesh-ext
          containerPort: 8080
          protocol: TCP
        - name: mesh-int
          containerPort: 8081
          protocol: TCP
        env:
        - name: ASYA_MESH_API_EXT_PORT
          value: "8080"
        - name: ASYA_MESH_API_INT_PORT
          value: "8081"
        - name: ASYA_INTERNAL_URL
          value: {{ include "asya-gateway.internalURL" . | quote }}
        - name: ASYA_STATE_PROXY_SOCKET
          value: {{ printf "%s/state-proxy.sock" .Values.stateProxy.mesh.socketDir | quote }}
        {{- /* Transport env vars from configmap */}}
        envFrom:
        - configMapRef:
            name: {{ include "asya-gateway.fullname" . }}
        {{- if .Values.tracing.endpoint }}
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: {{ .Values.tracing.endpoint | quote }}
        {{- end }}
        livenessProbe:
          httpGet:
            path: /health
            port: mesh-ext
          initialDelaySeconds: 5
          periodSeconds: 15
        readinessProbe:
          httpGet:
            path: /health
            port: mesh-ext
          initialDelaySeconds: 3
          periodSeconds: 5
        resources:
          {{- toYaml .Values.meshApi.resources | nindent 12 }}
        volumeMounts:
        - name: state-proxy-mesh-socket
          mountPath: {{ .Values.stateProxy.mesh.socketDir }}

      # --- state-proxy-pg: PG connector sidecar ---
      - name: state-proxy-mesh
        image: "{{ .Values.stateProxy.mesh.image.repository }}:{{ .Values.stateProxy.mesh.image.tag | default .Chart.AppVersion }}"
        imagePullPolicy: {{ .Values.stateProxy.mesh.image.pullPolicy }}
        env:
        - name: STATE_PROXY_SOCKET
          value: {{ printf "%s/state-proxy.sock" .Values.stateProxy.mesh.socketDir | quote }}
        - name: STATE_PROXY_PG_INDEXES
          value: {{ .Values.stateProxy.mesh.indexes | quote }}
        {{- if .Values.database.existingSecret }}
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {{ .Values.database.existingSecret }}
              key: {{ .Values.database.existingSecretKey }}
        {{- else }}
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: {{ include "asya-gateway.fullname" . }}-db
              key: password
        {{- end }}
        - name: STATE_PROXY_PG_URL
          value: "postgresql://{{ .Values.database.username }}:$(DB_PASSWORD)@{{ .Values.database.host }}:{{ .Values.database.port }}/{{ .Values.database.name }}?sslmode={{ .Values.database.sslMode }}"
        livenessProbe:
          exec:
            command: ["/bin/sh", "-c", "test -S {{ .Values.stateProxy.mesh.socketDir }}/state-proxy.sock"]
          initialDelaySeconds: 5
          periodSeconds: 10
        resources:
          {{- toYaml .Values.stateProxy.mesh.resources | nindent 12 }}
        volumeMounts:
        - name: state-proxy-mesh-socket
          mountPath: {{ .Values.stateProxy.mesh.socketDir }}

      {{- if .Values.mcp.enabled }}
      # --- mcp-adapter: MCP Streamable HTTP ---
      - name: mcp-adapter
        securityContext:
          {{- toYaml .Values.securityContext | nindent 12 }}
        image: "{{ .Values.mcp.image.repository }}:{{ .Values.mcp.image.tag | default .Chart.AppVersion }}"
        imagePullPolicy: {{ .Values.mcp.image.pullPolicy }}
        ports:
        - name: mcp
          containerPort: 8082
          protocol: TCP
        env:
        - name: ASYA_MCP_PORT
          value: "8082"
        - name: ASYA_MESH_API_URL
          value: "http://127.0.0.1:8080"
        - name: ASYA_MCP_TOOLS_PATH
          value: "/etc/asya/mcp"
        livenessProbe:
          httpGet:
            path: /health
            port: mcp
          initialDelaySeconds: 5
          periodSeconds: 15
        readinessProbe:
          httpGet:
            path: /health
            port: mcp
          initialDelaySeconds: 3
          periodSeconds: 5
        resources:
          {{- toYaml .Values.mcp.resources | nindent 12 }}
        volumeMounts:
        - name: mcp-tools
          mountPath: /etc/asya/mcp
          readOnly: true
      {{- end }}

      {{- if .Values.a2a.enabled }}
      # --- a2a-adapter: A2A JSON-RPC ---
      - name: a2a-adapter
        securityContext:
          {{- toYaml .Values.securityContext | nindent 12 }}
        image: "{{ .Values.a2a.image.repository }}:{{ .Values.a2a.image.tag | default .Chart.AppVersion }}"
        imagePullPolicy: {{ .Values.a2a.image.pullPolicy }}
        ports:
        - name: a2a
          containerPort: 8083
          protocol: TCP
        env:
        - name: ASYA_A2A_PORT
          value: "8083"
        - name: ASYA_MESH_API_URL
          value: "http://127.0.0.1:8080"
        - name: ASYA_A2A_AGENTS_PATH
          value: "/etc/asya/a2a"
        {{- if .Values.stateProxy.envelopes.enabled }}
        - name: ASYA_ENVELOPE_PROXY_SOCKET
          value: {{ printf "%s/state-proxy.sock" .Values.stateProxy.envelopes.socketDir | quote }}
        {{- end }}
        livenessProbe:
          httpGet:
            path: /health
            port: a2a
          initialDelaySeconds: 5
          periodSeconds: 15
        readinessProbe:
          httpGet:
            path: /health
            port: a2a
          initialDelaySeconds: 3
          periodSeconds: 5
        resources:
          {{- toYaml .Values.a2a.resources | nindent 12 }}
        volumeMounts:
        - name: a2a-agents
          mountPath: /etc/asya/a2a
          readOnly: true
        {{- if .Values.stateProxy.envelopes.enabled }}
        - name: state-proxy-envelopes-socket
          mountPath: {{ .Values.stateProxy.envelopes.socketDir }}
        {{- end }}
      {{- end }}

      {{- if .Values.stateProxy.envelopes.enabled }}
      # --- state-proxy-envelopes: S3 connector for A2A history ---
      - name: state-proxy-envelopes
        image: "{{ .Values.stateProxy.envelopes.image.repository }}:{{ .Values.stateProxy.envelopes.image.tag | default .Chart.AppVersion }}"
        imagePullPolicy: {{ .Values.stateProxy.envelopes.image.pullPolicy }}
        env:
        - name: STATE_PROXY_SOCKET
          value: {{ printf "%s/state-proxy.sock" .Values.stateProxy.envelopes.socketDir | quote }}
        - name: STATE_PROXY_BUCKET
          value: {{ .Values.stateProxy.envelopes.config.bucket | quote }}
        - name: STATE_PROXY_REGION
          value: {{ .Values.stateProxy.envelopes.config.region | quote }}
        {{- with .Values.stateProxy.envelopes.config.endpoint }}
        - name: STATE_PROXY_ENDPOINT
          value: {{ . | quote }}
        {{- end }}
        resources:
          {{- toYaml .Values.stateProxy.envelopes.resources | nindent 12 }}
        volumeMounts:
        - name: state-proxy-envelopes-socket
          mountPath: {{ .Values.stateProxy.envelopes.socketDir }}
      {{- end }}

      volumes:
      - name: state-proxy-mesh-socket
        emptyDir: {}
      {{- if .Values.mcp.enabled }}
      - name: mcp-tools
        configMap:
          name: {{ include "asya-gateway.fullname" . }}-mcp-tools
          optional: true
      {{- end }}
      {{- if .Values.a2a.enabled }}
      - name: a2a-agents
        configMap:
          name: {{ include "asya-gateway.fullname" . }}-a2a-agents
          optional: true
      {{- end }}
      {{- if .Values.stateProxy.envelopes.enabled }}
      - name: state-proxy-envelopes-socket
        emptyDir: {}
      {{- end }}
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
```

Design decisions:
- **Single Deployment**: mesh-api + adapters + state-proxies share one pod.
  SSE and sidecar callbacks in same process (Go channels, no pg_notify).
- **Two ports on mesh-api**: 8080 (ext) for client requests, 8081 (int) for
  sidecar callbacks. Same binary, different auth boundaries.
- **Adapters talk to mesh-api via localhost**: `http://127.0.0.1:8080` (same pod,
  no network hop). For hash-routed SSE, they go via Ingress with
  `URI-extracted envelope ID` header.
- **state-proxy-mesh over Unix socket**: mesh-api talks to PG through the
  state-proxy HTTP API over Unix socket. No PG driver in mesh-api binary.
- **terminationGracePeriodSeconds: 35**: 30s for SSE drain + 5s buffer.
- **Adapter volumes**: ConfigMaps mounted at `/etc/asya/mcp/` and
  `/etc/asya/a2a/`. Kubelet syncs in ~10s, adapters poll for changes.

### 1.4 Services — Four Service Resources

Delete `service-api.yaml` and `service-mesh.yaml`. Create four Service templates.

**service-mesh-api.yaml** — External mesh-api (client-facing):
```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "asya-gateway.meshApi.fullname" . }}
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: mesh-api
spec:
  type: {{ .Values.service.type }}
  ports:
  - port: {{ .Values.service.meshApi.port }}
    targetPort: mesh-ext
    protocol: TCP
    name: http
  selector:
    {{- include "asya-gateway.selectorLabels" . | nindent 4 }}
```

**service-mesh-api-int.yaml** — Internal mesh-api (sidecar callbacks):
```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "asya-gateway.meshApiInt.fullname" . }}
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: mesh-api-int
spec:
  type: {{ .Values.service.meshApiInternal.type }}
  ports:
  - port: {{ .Values.service.meshApiInternal.port }}
    targetPort: mesh-int
    protocol: TCP
    name: http
  selector:
    {{- include "asya-gateway.selectorLabels" . | nindent 4 }}
```

**service-mcp.yaml** (conditional on `mcp.enabled`):
```yaml
{{- if .Values.mcp.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "asya-gateway.mcp.fullname" . }}
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: mcp
spec:
  type: {{ .Values.service.type }}
  ports:
  - port: {{ .Values.service.mcp.port }}
    targetPort: mcp
    protocol: TCP
    name: http
  selector:
    {{- include "asya-gateway.selectorLabels" . | nindent 4 }}
{{- end }}
```

**service-a2a.yaml** (conditional on `a2a.enabled`):
```yaml
{{- if .Values.a2a.enabled }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "asya-gateway.a2a.fullname" . }}
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: a2a
spec:
  type: {{ .Values.service.type }}
  ports:
  - port: {{ .Values.service.a2a.port }}
    targetPort: a2a
    protocol: TCP
    name: http
  selector:
    {{- include "asya-gateway.selectorLabels" . | nindent 4 }}
{{- end }}
```

### 1.5 ConfigMaps

**configmap.yaml** — Transport config for mesh-api (replace existing):
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "asya-gateway.fullname" . }}
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
data:
  {{- if .Values.transports.rabbitmq.enabled }}
  ASYA_TRANSPORT: "rabbitmq"
  ASYA_RABBITMQ_URL: {{ .Values.transports.rabbitmq.config.url | quote }}
  ASYA_RABBITMQ_EXCHANGE: {{ .Values.transports.rabbitmq.config.exchange | quote }}
  ASYA_RABBITMQ_POOL_SIZE: {{ .Values.transports.rabbitmq.config.poolSize | quote }}
  {{- end }}
  {{- if .Values.transports.sqs.enabled }}
  ASYA_TRANSPORT: "sqs"
  ASYA_SQS_ENDPOINT: {{ .Values.transports.sqs.config.endpoint | quote }}
  ASYA_SQS_REGION: {{ .Values.transports.sqs.config.region | quote }}
  ASYA_SQS_VISIBILITY_TIMEOUT: {{ .Values.transports.sqs.config.visibilityTimeout | quote }}
  ASYA_SQS_WAIT_TIME_SECONDS: {{ .Values.transports.sqs.config.waitTimeSeconds | quote }}
  {{- end }}
  {{- if .Values.transports.pubsub.enabled }}
  ASYA_TRANSPORT: "pubsub"
  ASYA_PUBSUB_PROJECT_ID: {{ .Values.transports.pubsub.config.projectId | quote }}
  {{- with .Values.transports.pubsub.config.endpoint }}
  ASYA_PUBSUB_ENDPOINT: {{ . | quote }}
  {{- end }}
  {{- end }}
```

**configmap-mcp-tools.yaml** — MCP tool definitions (new):
```yaml
{{- if .Values.mcp.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "asya-gateway.fullname" . }}-mcp-tools
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: mcp
    asya.sh/config-type: mcp-tools
data:
  tools.yaml: |
    tools:
    {{- if .Values.mcpTools }}
    {{- .Values.mcpTools | toYaml | nindent 4 }}
    {{- end }}
{{- end }}
```

**configmap-a2a-agents.yaml** — A2A agent definitions (new):
```yaml
{{- if .Values.a2a.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "asya-gateway.fullname" . }}-a2a-agents
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: a2a
    asya.sh/config-type: a2a-agents
data:
  agents.yaml: |
    agents:
    {{- if .Values.a2aAgents }}
    {{- .Values.a2aAgents | toYaml | nindent 4 }}
    {{- end }}
{{- end }}
```

### 1.6 Secret

**secret.yaml** — DB password (replace existing):
```yaml
{{- if and .Values.database.host (not .Values.database.existingSecret) }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "asya-gateway.fullname" . }}-db
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
type: Opaque
stringData:
  password: {{ .Values.database.password | quote }}
{{- end }}
```

Remove the `helm.sh/hook` annotations from the secret. The state-proxy-pg handles
schema creation on startup (CREATE TABLE IF NOT EXISTS), so no migration job needed.

### 1.7 PodDisruptionBudget (new)

**pdb.yaml**:
```yaml
{{- if .Values.podDisruptionBudget.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "asya-gateway.fullname" . }}
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
spec:
  maxUnavailable: {{ .Values.podDisruptionBudget.maxUnavailable }}
  selector:
    matchLabels:
      {{- include "asya-gateway.selectorLabels" . | nindent 6 }}
{{- end }}
```

### 1.8 Templates to Delete

- `deployment-api.yaml` (replaced by `deployment.yaml`)
- `deployment-mesh.yaml` (replaced by `deployment.yaml`)
- `service-api.yaml` (replaced by 4 service files)
- `service-mesh.yaml` (replaced by 4 service files)
- `db-migration-job.yaml` (state-proxy-pg auto-creates schema)
- `configmap-flows.yaml` (flows are actor-side, not gateway-side)
- `rbac-flow-exposer.yaml` (flow exposure via ConfigMaps is adapter concern)

### 1.9 Templates to Keep (unchanged or minor edits)

- `serviceaccount.yaml` — unchanged
- `tests/` — rewrite (see section 1.11)

### 1.10 Chart.yaml Update

```yaml
apiVersion: v2
name: asya-gateway
description: Asya mesh-api + protocol adapters (MCP, A2A) gateway
type: application
version: 0.0.0
appVersion: "0.0.0"
```

### 1.11 Helm Tests (Rewrite)

Delete existing test templates. Create new ones:

**tests/test-mesh-api-health.yaml**:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "asya-gateway.fullname" . }}-test-health"
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  restartPolicy: Never
  containers:
  - name: test
    image: {{ .Values.tests.image }}
    imagePullPolicy: {{ .Values.tests.imagePullPolicy }}
    command: ['/bin/sh', '-c']
    args:
    - |
      set -e
      echo "[.] Testing mesh-api external health..."
      wget --spider -S http://{{ include "asya-gateway.meshApi.fullname" . }}:{{ .Values.service.meshApi.port }}/health
      echo "[+] External health OK"

      echo "[.] Testing mesh-api internal health..."
      wget --spider -S http://{{ include "asya-gateway.meshApiInt.fullname" . }}:{{ .Values.service.meshApiInternal.port }}/health
      echo "[+] Internal health OK"
```

**tests/test-mesh-api-crud.yaml** — Create + Get + Delete message:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "asya-gateway.fullname" . }}-test-crud"
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  restartPolicy: Never
  containers:
  - name: test
    image: {{ .Values.tests.image }}
    imagePullPolicy: {{ .Values.tests.imagePullPolicy }}
    command: ['/bin/sh', '-c']
    args:
    - |
      set -e
      MESH_URL="http://{{ include "asya-gateway.meshApi.fullname" . }}:{{ .Values.service.meshApi.port }}"

      echo "[.] Creating test message..."
      CREATE_RESP=$(curl -sf -X POST "$MESH_URL/api/v1/mesh/?actor=test-nonexistent" \
        -H "Content-Type: application/json" \
        -d '{"payload":{"test":true},"headers":{},"timeout":60}')
      MSG_ID=$(echo "$CREATE_RESP" | jq -r '.id')
      echo "[+] Created message: $MSG_ID"

      echo "[.] Getting message status..."
      GET_RESP=$(curl -sf "$MESH_URL/api/v1/mesh/$MSG_ID")
      STATUS=$(echo "$GET_RESP" | jq -r '.status')
      echo "[+] Status: $STATUS"

      echo "[.] Deleting message..."
      curl -sf -X DELETE "$MESH_URL/api/v1/mesh/$MSG_ID"
      echo "[+] Deleted"

      echo "[.] Verifying deletion..."
      GET_AFTER=$(curl -s -w "%{http_code}" -o /dev/null "$MESH_URL/api/v1/mesh/$MSG_ID")
      if [ "$GET_AFTER" = "404" ] || [ "$GET_AFTER" = "200" ]; then
        echo "[+] CRUD test passed"
      else
        echo "[-] Unexpected status code: $GET_AFTER"
        exit 1
      fi
```

**tests/test-mcp-adapter.yaml** (conditional):
```yaml
{{- if .Values.mcp.enabled }}
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "asya-gateway.fullname" . }}-test-mcp"
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-weight": "2"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  restartPolicy: Never
  containers:
  - name: test
    image: {{ .Values.tests.image }}
    imagePullPolicy: {{ .Values.tests.imagePullPolicy }}
    command: ['/bin/sh', '-c']
    args:
    - |
      set -e
      MCP_URL="http://{{ include "asya-gateway.mcp.fullname" . }}:{{ .Values.service.mcp.port }}"

      echo "[.] Testing MCP initialize..."
      RESP=$(curl -sf -X POST "$MCP_URL/mcp" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"helm-test","version":"1.0.0"}}}')
      echo "[+] MCP initialize: $RESP"

      echo "[.] Testing MCP tools/list..."
      TOOLS=$(curl -sf -X POST "$MCP_URL/mcp" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')
      echo "[+] MCP tools/list: $TOOLS"
{{- end }}
```

---

## 2. nginx Ingress Templates

### 2.1 ingress-external-create.yaml — Round-Robin for Task Creation

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "asya-gateway.fullname" . }}-create
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: ingress-create
  annotations:
    {{- with .Values.ingress.annotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- with .Values.ingress.className }}
  ingressClassName: {{ . }}
  {{- end }}
  {{- with .Values.ingress.tls }}
  tls:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  rules:
  - {{- with .Values.ingress.host }}
    host: {{ . }}
    {{- end }}
    http:
      paths:
      - path: /api/v1/mesh/
        pathType: Exact
        backend:
          service:
            name: {{ include "asya-gateway.meshApi.fullname" . }}
            port:
              number: {{ .Values.service.meshApi.port }}
{{- end }}
```

**Why Exact pathType**: `POST /api/v1/mesh/?actor=foo` matches Exact because
the query string is not part of the path. nginx Ingress sends trailing-slash
Exact as `=` location. No ID yet, so round-robin (no hash annotation).

### 2.2 ingress-external-sticky.yaml — Hash-Routed for ID-Bearing Requests

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "asya-gateway.fullname" . }}-sticky
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: ingress-sticky
  annotations:
    nginx.ingress.kubernetes.io/upstream-hash-by: "$envelope_id"
    {{- with .Values.ingress.annotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- with .Values.ingress.className }}
  ingressClassName: {{ . }}
  {{- end }}
  {{- with .Values.ingress.tls }}
  tls:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  rules:
  - {{- with .Values.ingress.host }}
    host: {{ . }}
    {{- end }}
    http:
      paths:
      - path: /api/v1/mesh/
        pathType: Prefix
        backend:
          service:
            name: {{ include "asya-gateway.meshApi.fullname" . }}
            port:
              number: {{ .Values.service.meshApi.port }}
      {{- if .Values.mcp.enabled }}
      - path: /mcp/
        pathType: Prefix
        backend:
          service:
            name: {{ include "asya-gateway.mcp.fullname" . }}
            port:
              number: {{ .Values.service.mcp.port }}
      {{- end }}
      {{- if .Values.a2a.enabled }}
      - path: /a2a/
        pathType: Prefix
        backend:
          service:
            name: {{ include "asya-gateway.a2a.fullname" . }}
            port:
              number: {{ .Values.service.a2a.port }}
      {{- end }}
{{- end }}
```

**Path precedence**: nginx Ingress controller merges rules across Ingress
resources. `Exact` has higher priority than `Prefix` for the same path. So
`POST /api/v1/mesh/` (no ID, Exact match) goes round-robin, while
`GET /api/v1/mesh/abc123/events` (has ID, Prefix match) goes hash-routed.

### 2.3 ingress-internal.yaml — Sidecar Callbacks (Hash-Routed)

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "asya-gateway.fullname" . }}-internal
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
    app.kubernetes.io/component: ingress-internal
  annotations:
    nginx.ingress.kubernetes.io/upstream-hash-by: "$envelope_id"
    {{- with .Values.ingress.internalAnnotations }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  {{- with .Values.ingress.className }}
  ingressClassName: {{ . }}
  {{- end }}
  rules:
  - {{- with .Values.ingress.internalHost }}
    host: {{ . }}
    {{- end }}
    http:
      paths:
      - path: /api/v1/mesh/
        pathType: Prefix
        backend:
          service:
            name: {{ include "asya-gateway.meshApiInt.fullname" . }}
            port:
              number: {{ .Values.service.meshApiInternal.port }}
{{- end }}
```

### 2.4 networkpolicy.yaml — Internal Port Protection

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "asya-gateway.fullname" . }}-internal
  labels:
    {{- include "asya-gateway.labels" . | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      {{- include "asya-gateway.selectorLabels" . | nindent 6 }}
  policyTypes:
  - Ingress
  ingress:
  # External ports (8080, 8082, 8083): allow from anywhere
  - ports:
    - port: 8080
      protocol: TCP
    {{- if .Values.mcp.enabled }}
    - port: 8082
      protocol: TCP
    {{- end }}
    {{- if .Values.a2a.enabled }}
    - port: 8083
      protocol: TCP
    {{- end }}
  # Internal port (8081): only from pods in the actor namespace
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: {{ .Release.Namespace }}
    ports:
    - port: 8081
      protocol: TCP
{{- end }}
```

**Note**: The NetworkPolicy allows internal port 8081 from pods within the
release namespace. In production, the `from` selector should match the actor
namespace via `ingress.internalAnnotations` if actors are in a different
namespace. For E2E tests, actors and gateway are in the same namespace.

### 2.5 Ingress Routing Summary

```
Client -> POST /api/v1/mesh/?actor=foo
  -> External Ingress (Exact /api/v1/mesh/) -> round-robin -> any mesh-api pod
  -> Returns {id: "abc123"}

Client -> GET /api/v1/mesh/abc123/events (URI-extracted envelope ID: abc123)
  -> External Ingress (Prefix /api/v1/mesh/) -> hash(abc123) -> mesh-api pod X
  -> SSE stream

Sidecar -> POST /api/v1/mesh/abc123/events (URI-extracted envelope ID: abc123)
  -> Internal Ingress (Prefix /api/v1/mesh/) -> hash(abc123) -> mesh-api pod X
  -> 204

Both SSE subscriber and sidecar publisher land on the same pod.
Go channel delivers events in-process. No pg_notify needed.
```

---

## 3. Crossplane Composition Changes

### 3.1 Remove ASYA_GATEWAY_URL from Actor Pods

Three files to modify:
- `deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml`
- `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml`
- `deploy/helm-charts/asya-crossplane/templates/composition-pubsub.yaml`

In each file, remove the `$gatewayURL` variable declaration and the
ASYA_GATEWAY_URL env var block.

**composition-rabbitmq.yaml**: Remove lines ~254 (`$gatewayURL` variable) and
lines ~416-419 (ASYA_GATEWAY_URL env var block):
```
# DELETE this line (~254):
{{`{{- $gatewayURL := "`}}{{ .Values.sidecar.gatewayURL }}{{`" -}}`}}

# DELETE this block (~416-419):
{{`{{- if ne $gatewayURL "" }}`}}
- name: ASYA_GATEWAY_URL
  value: {{`{{ $gatewayURL }}`}}
{{`{{- end }}`}}
```

**composition-sqs.yaml**: Remove lines ~366 and ~542-545 (same pattern).

**composition-pubsub.yaml**: Remove lines ~350 and ~516-519 (same pattern).

### 3.2 Remove gatewayURL from values.yaml

In `deploy/helm-charts/asya-crossplane/values.yaml`, remove:
```yaml
  # Gateway URL for progress reporting (leave empty to disable)
  gatewayURL: ""
```

### 3.3 Backward Compatibility

The sidecar (PR3) reads `x-asya-gateway-url` from the envelope header, falling
back to `ASYA_GATEWAY_URL` env var. After PR4:
- New envelopes: mesh-api stamps `x-asya-gateway-url` in the header
- Old envelopes (in-flight during upgrade): sidecar falls back to env var
- After all in-flight envelopes drain: env var is unused

For the transition period, operators can set ASYA_GATEWAY_URL via
`sidecar.env` in the AsyncActor spec (per-actor override). This is NOT a
chart-level value anymore.

### 3.4 Cascade Check

Grep ALL files for `gatewayURL` and `ASYA_GATEWAY_URL` to find remaining
references. Known locations to update:

- `testing/e2e/profiles/*.yaml` — remove `sidecar.gatewayURL` from crossplane
  section, remove `ASYA_GATEWAY_URL` from crew actor env
- `testing/e2e/charts/values.yaml` — remove `ASYA_GATEWAY_URL` from crew
  section
- `testing/shared/compose/asya/*.yml` — remove or leave (Docker Compose tests
  are not affected by Crossplane changes, and the sidecar still supports the
  env var as fallback)
- `docs/reference/env-vars.md` — mark `ASYA_GATEWAY_URL` as deprecated
- `docs/reference/components/core-sidecar.md` — update
- `testing/e2e/profiles/.env.*` — remove `ASYA_GATEWAY_URL` lines if present

---

## 4. E2E Test Infrastructure

### 4.1 E2E Profile Updates

**testing/e2e/profiles/rabbitmq-minio.yaml** changes:
```yaml
# BEFORE:
gateway:
  transports:
    rabbitmq:
      enabled: true
      config:
        url: amqp://guest:guest@asya-rabbitmq.asya-e2e.svc.cluster.local:5672/
        ...
  env:
  - name: ASYA_A2A_API_KEY
    ...

# AFTER:
gateway:
  meshApi:
    image:
      pullPolicy: Never
  mcp:
    enabled: true
    image:
      pullPolicy: Never
  a2a:
    enabled: true
    image:
      pullPolicy: Never
  stateProxy:
    mesh:
      image:
        pullPolicy: Never
  database:
    host: asya-gateway-postgresql.asya-e2e.svc.cluster.local
    port: 5432
    name: asya_gateway
    username: asya
    password: asya-db-password
  transports:
    rabbitmq:
      enabled: true
      config:
        url: amqp://guest:guest@asya-rabbitmq.asya-e2e.svc.cluster.local:5672/
        exchange: asya
        poolSize: 20
    sqs:
      enabled: false
  mcpTools:
  - name: test_echo
    description: "Echo test"
    actor: test-echo
    timeout: 60
  a2aAgents:
  - name: test-agent
    description: "Test A2A agent"
    actor: test-echo
    timeout: 60
    streaming: true
    skills:
    - id: echo
      name: Echo
      description: "Echo back input"
    inputModes: [text/plain, application/json]
    outputModes: [text/plain, application/json]

crossplane:
  transport: rabbitmq
  sidecar:
    image: ghcr.io/deliveryhero/asya-sidecar:latest
    imagePullPolicy: Never
    # gatewayURL REMOVED - envelope header used instead
    rabbitmqURL: amqp://guest:guest@asya-rabbitmq.asya-e2e.svc.cluster.local:5672/
  ...

crew:
  x-sink:
    env:
      # ASYA_GATEWAY_URL REMOVED - envelope header used instead
      ASYA_PERSISTENCE_MOUNT: "/state/checkpoints/results"
      ...
  x-sump:
    env:
      # ASYA_GATEWAY_URL REMOVED
      ASYA_PERSISTENCE_MOUNT: "/state/checkpoints/errors"
      ...
```

Same pattern for `sqs-s3.yaml` and `pubsub-gcs.yaml`.

### 4.2 E2E Values Updates

**testing/e2e/charts/values.yaml** changes:
```yaml
gateway:
  meshApi:
    image:
      repository: ghcr.io/deliveryhero/asya-mesh-api
      tag: latest
      pullPolicy: Never
  mcp:
    enabled: true
    image:
      repository: ghcr.io/deliveryhero/asya-mcp-adapter
      tag: latest
      pullPolicy: Never
  a2a:
    enabled: true
    image:
      repository: ghcr.io/deliveryhero/asya-a2a-adapter
      tag: latest
      pullPolicy: Never
  stateProxy:
    mesh:
      image:
        repository: ghcr.io/deliveryhero/asya-state-proxy-pg
        tag: latest
        pullPolicy: Never
  database:
    host: asya-gateway-postgresql.asya-e2e.svc.cluster.local
    ...
  service:
    type: NodePort
    meshApi:
      port: 8080
      nodePort: 30080
    meshApiInternal:
      port: 8081
      type: ClusterIP
    mcp:
      port: 8082
    a2a:
      port: 8083
  tests:
    image: ghcr.io/deliveryhero/asya-testing:latest
    imagePullPolicy: Never
  replicaCount: 1
```

### 4.3 Deploy Script Updates

**testing/e2e/scripts/deploy.sh** changes:
- Build images: add `asya-mesh-api`, `asya-mcp-adapter`, `asya-a2a-adapter`,
  `asya-state-proxy-pg` to the build list
- Kind load: add new images to `IMAGES_TO_LOAD` array
- Phase 9b: remove flow registration (flows are adapter ConfigMaps now, seeded
  via Helm values)

### 4.4 Test Helper Updates

**src/asya-testing/asya_testing/fixtures/gateway.py** — update gateway URL
construction to use mesh-api service name:
- `ASYA_GATEWAY_URL` env var should point to the NodePort for mesh-api
  external port (30080)
- Add `ASYA_MCP_URL` and `ASYA_A2A_URL` for adapter endpoints

**src/asya-testing/asya_testing/config.py** — add mesh API URL config.

### 4.5 Helmfile Changes

**testing/e2e/charts/helmfile.yaml.gotmpl**:
- Update the `asya-gateway` release to use new values structure
- Remove `set` overrides for old `postgresql.*` and `externalDatabase.*` keys
- Use new `database.*` keys instead
- Remove `exposedFlows` from the release values

---

## 5. E2E Test Scenarios

### 5.1 test_mesh_api_e2e.py — Core Mesh API Tests

New test file: `testing/e2e/tests/test_mesh_api_e2e.py`

```python
"""
E2E tests for the new mesh API (/api/v1/mesh/).

Tests the two-step dispatch pattern: POST create -> GET /events subscribe.
"""

class TestMeshApiCreate:
    """POST /api/v1/mesh/?actor={name} creates message, dispatches to queue."""

    def test_create_returns_id(self, e2e_helper):
        """POST returns 201 with {id: "..."}."""

    def test_create_with_headers(self, e2e_helper):
        """Custom headers are stamped into envelope."""

    def test_create_stamps_gateway_url(self, e2e_helper):
        """Envelope contains x-asya-gateway-url header."""

    def test_create_invalid_actor_returns_400(self, e2e_helper):
        """Missing actor query param returns 400."""


class TestMeshApiGet:
    """GET /api/v1/mesh/{id} returns message status."""

    def test_get_pending_message(self, e2e_helper):
        """Newly created message has status pending."""

    def test_get_nonexistent_returns_404(self, e2e_helper):
        """Unknown ID returns 404."""


class TestMeshApiEvents:
    """GET /api/v1/mesh/{id}/events streams SSE."""

    def test_sse_receives_status_updates(self, e2e_helper):
        """SSE stream receives running -> succeeded events."""

    def test_sse_receives_fly_events(self, e2e_helper):
        """FLY events arrive via SSE."""

    def test_sse_catchup_on_reconnect(self, e2e_helper):
        """Reconnect after disconnect catches up from DB."""

    def test_sse_terminal_closes_stream(self, e2e_helper):
        """SSE stream closes after terminal status."""


class TestMeshApiCancel:
    """DELETE /api/v1/mesh/{id} cancels message."""

    def test_cancel_running_message(self, e2e_helper):
        """Cancel changes status to canceled."""


class TestMeshApiList:
    """GET /api/v1/mesh/ lists messages."""

    def test_list_with_status_filter(self, e2e_helper):
        """Filter by status=running."""

    def test_list_pagination(self, e2e_helper):
        """Limit and offset work."""
```

### 5.2 test_mcp_adapter_e2e.py — MCP Protocol Tests

New test file or update existing `test_gateway_routing_e2e.py`:

```python
"""
E2E tests for MCP adapter integration.

Tests the full flow: MCP tools/call -> mesh-api -> actor -> sidecar -> SSE -> MCP result.
"""

class TestMcpToolsCall:
    """MCP tools/call dispatches to mesh and returns result."""

    def test_tools_call_simple_actor(self, e2e_helper):
        """
        Full flow:
        1. MCP tools/call "test_echo" {input: "hello"}
        2. MCP adapter POSTs to mesh-api (round-robin)
        3. mesh-api dispatches to test-echo queue
        4. Sidecar processes, POSTs status events back to mesh-api (hash-routed)
        5. MCP adapter receives SSE events
        6. MCP adapter returns CallToolResult to client
        """

    def test_tools_call_with_progress(self, e2e_helper):
        """Status events translate to MCP progress notifications."""

    def test_tools_call_fly_events(self, e2e_helper):
        """FLY events translate to MCP log notifications."""


class TestMcpToolsList:
    """MCP tools/list returns tools from ConfigMap."""

    def test_list_returns_configured_tools(self, e2e_helper):
        """Tools from mcpTools values appear in tools/list."""

    def test_hot_reload_detects_new_tools(self, e2e_helper):
        """Patching ConfigMap adds new tools within polling interval."""
```

### 5.3 test_a2a_adapter_e2e.py — A2A Protocol Tests

Update existing `testing/e2e/tests/test_a2a_e2e.py`:

```python
"""
E2E tests for A2A adapter integration.
"""

class TestA2ATasksSend:
    """A2A tasks/send dispatches to mesh and returns task."""

    def test_send_creates_task(self, e2e_helper):
        """tasks/send creates message via mesh-api."""

    def test_send_subscribe_streams_events(self, e2e_helper):
        """tasks/sendSubscribe returns SSE stream with A2A events."""


class TestA2ATasksGet:
    """A2A tasks/get returns task status."""

    def test_get_maps_mesh_status_to_a2a_state(self, e2e_helper):
        """running -> working, succeeded -> completed."""


class TestA2AAgentCard:
    """Agent card served from ConfigMap."""

    def test_agent_card_from_configmap(self, e2e_helper):
        """/.well-known/agent.json returns configured agent."""
```

### 5.4 test_envelope_gateway_url_e2e.py — Header Injection Tests

New test file: `testing/e2e/tests/test_envelope_gateway_url_e2e.py`

```python
"""
E2E tests for x-asya-gateway-url envelope header.

Verifies that the sidecar reads gateway URL from envelope (not env var)
and that removing ASYA_GATEWAY_URL from Crossplane doesn't break actors.
"""

class TestEnvelopeGatewayUrl:
    """Sidecar uses x-asya-gateway-url from envelope header."""

    def test_sidecar_posts_to_envelope_url(self, e2e_helper):
        """
        1. POST /api/v1/mesh/?actor=test-echo
        2. Verify envelope has x-asya-gateway-url header
        3. Actor processes successfully (sidecar uses header URL)
        4. Status events arrive at mesh-api
        """

    def test_no_gateway_url_env_var_in_actor_pod(self, e2e_helper):
        """
        kubectl exec into actor pod, verify ASYA_GATEWAY_URL is not set.
        Proves Crossplane composition no longer injects it.
        """
```

### 5.5 test_consistent_hash_e2e.py — Hash Routing Tests

New test file (only runs when Ingress is enabled, may be Kind-only):

```python
"""
E2E tests for consistent hash routing via nginx Ingress.
"""

class TestConsistentHash:
    """URI-extracted envelope ID routes SSE and sidecar POSTs to same pod."""

    def test_sse_and_sidecar_converge_on_same_pod(self, e2e_helper):
        """
        With replicaCount=2:
        1. Create message (round-robin)
        2. Subscribe SSE with URI-extracted envelope ID (hash-routed)
        3. Sidecar POSTs events with same header (hash-routed)
        4. SSE receives events (proves same pod)
        """

    def test_reconnect_after_pod_restart_catches_up(self, e2e_helper):
        """
        1. Create message, subscribe SSE
        2. Kill the target pod
        3. Reconnect SSE (hash ring rebalances)
        4. Catch up from DB
        """
```

**Note**: Consistent hash tests require nginx Ingress controller in the Kind
cluster. If not available, mark as `@pytest.mark.skip(reason="requires nginx ingress")`.
The Kind cluster kind-config.yaml may need an nginx Ingress controller added
to the E2E infrastructure.

### 5.6 Full Integration Flow Test

The most important test — exercises the entire pipeline:

```python
def test_full_mcp_flow_e2e(self, e2e_helper):
    """
    Complete end-to-end: MCP client -> adapter -> mesh-api -> queue ->
    actor -> sidecar -> mesh-api events -> SSE -> MCP client

    1. POST MCP tools/call to adapter (port 8082)
    2. Adapter creates message via mesh-api (port 8080)
    3. Adapter subscribes to SSE via mesh-api (port 8080, hash-routed)
    4. mesh-api dispatches envelope to actor queue
    5. Sidecar receives envelope from queue
    6. Sidecar reads x-asya-gateway-url from envelope headers
    7. Sidecar POSTs running status to internal mesh-api (port 8081)
    8. Actor processes payload
    9. Sidecar POSTs succeeded status to internal mesh-api (port 8081)
    10. mesh-api notifies SSE subscriber (Go channel)
    11. Adapter translates to MCP CallToolResult
    12. Client receives result

    Assert: MCP response contains actor output, status transitions are
    monotonic (pending -> running -> succeeded), no ASYA_GATEWAY_URL env
    var on actor pod.
    """
```

---

## 6. Documentation

### 6.1 docs/setup/guide-gateway.md — Rewrite

Full rewrite of the existing guide. New structure:

```markdown
---
description: "Gateway setup: deploy mesh-api, MCP adapter, A2A adapter, Ingress, state-proxy-pg"
---

# Gateway Setup

## Architecture Overview
- Single Deployment: mesh-api + optional adapters + state-proxy sidecars
- Diagram: client -> Ingress -> mesh-api/mcp/a2a -> queue -> actors -> sidecar -> mesh-api

## Prerequisites
- Kubernetes cluster with kubectl access
- Helm 3.0+
- PostgreSQL database
- nginx Ingress controller (recommended)

## Quick Start
- helm install with minimal values (mesh-api only)

## Enabling MCP
- Set mcp.enabled=true
- Configure mcpTools in values.yaml
- Example tools/call

## Enabling A2A
- Set a2a.enabled=true
- Configure a2aAgents in values.yaml
- Example tasks/send

## Ingress Configuration
- External Ingress (round-robin + hash)
- Internal Ingress (sidecar callbacks)
- TLS configuration
- Authentication annotations

## Database Configuration
- External PostgreSQL
- Connection string format
- Expression indexes

## Scaling
- HPA configuration
- PodDisruptionBudget
- Consistent hash and rolling updates

## Monitoring
- Health endpoints per container
- Prometheus metrics
- Tracing configuration
```

### 6.2 docs/usage/guide-gateway.md — New Usage Guide

Cross-linked from setup guide.

```markdown
---
description: "Gateway usage: mesh API, MCP tools, A2A agents, SSE streaming, tool registration"
---

# Using the Gateway

## Mesh API (/api/v1/mesh/)
- Two-step pattern: create -> subscribe
- Create message: POST /api/v1/mesh/?actor={name}
- Subscribe to events: GET /api/v1/mesh/{id}/events
- Get status: GET /api/v1/mesh/{id}
- Cancel: DELETE /api/v1/mesh/{id}
- List: GET /api/v1/mesh/

## SSE Event Format
- event: status (status updates)
- event: fly (ephemeral streaming)
- Catch-up on reconnect

## MCP Integration
- tools/list, tools/call
- Progress notifications
- FLY -> log notifications

## A2A Integration
- tasks/send, tasks/subscribe, tasks/sendSubscribe
- Agent card from ConfigMap
- State mapping

## Registering Tools and Agents
- asya expose --as mcp
- asya expose --as a2a
- ConfigMap hot-reload

## Envelope Gateway URL Header
- x-asya-gateway-url eliminates ASYA_GATEWAY_URL env var
- Sidecar reads URL from envelope
- Multi-dispatcher scenarios
```

### 6.3 AGENTS.md Updates

Update the "Gateway Routes" section to reflect new architecture:

```markdown
### Gateway Routes (asya-gateway)

Single deployment with three containers:

| Container | Port | Routes | Purpose |
|-----------|------|--------|---------|
| mesh-api | :8080 (ext) | `/api/v1/mesh/*` | Client-facing mesh API |
| mesh-api | :8081 (int) | `/api/v1/mesh/*` | Sidecar callbacks (NetworkPolicy protected) |
| mcp-adapter | :8082 | `/mcp/*` | MCP Streamable HTTP (optional) |
| a2a-adapter | :8083 | `/a2a/*` | A2A JSON-RPC (optional) |

nginx Ingress routes:
- `/api/v1/mesh/` Exact -> round-robin (task creation)
- `/api/v1/mesh/` Prefix -> hash by URI-extracted envelope ID (SSE, status, events)
- `/mcp/` Prefix -> hash by URI-extracted envelope ID
- `/a2a/` Prefix -> hash by URI-extracted envelope ID

Special root routes:
- `/.well-known/agent.json` -> a2a-adapter (served from ConfigMap)
- `/health` -> mesh-api (K8s probe)
```

### 6.4 docs/reference/env-vars.md Update

Mark `ASYA_GATEWAY_URL` as deprecated:

```markdown
| `ASYA_GATEWAY_URL` | Sidecar | **Deprecated**. Gateway URL for status callbacks. Use `x-asya-gateway-url` envelope header instead. Env var retained as fallback for backward compatibility. |
```

---

## 7. Migration and Backward Compatibility

### 7.1 Migration Path

1. **PR1-PR3 merged**: new binaries exist but old chart still deploys old monolith
2. **PR4 merges**: Helm chart switches to multi-container deployment
3. `helm upgrade` replaces old Deployments with new single Deployment
4. Old `asya-gateway-api` and `asya-gateway-mesh` Deployments are deleted
   (selector label changes require `helm uninstall` + `helm install` or
   `--force` flag)
5. In-flight envelopes with `ASYA_GATEWAY_URL` env var: sidecar falls back to
   env var until the envelope is fully processed

### 7.2 Breaking Changes

- **Helm values schema change**: all `postgresql.*`, `externalDatabase.*`,
  `exposedFlows`, `flowConfigMaps`, `migration.*`, `config.port` keys are gone.
  Users must update their values files.
- **Service names change**: `asya-gateway-api` -> `asya-gateway-mesh-api`,
  `asya-gateway-mesh` -> `asya-gateway-mesh-api-int`. Any hardcoded references
  (Crossplane `sidecar.gatewayURL`, crew `ASYA_GATEWAY_URL` env) must update.
- **No Sqitch migration job**: state-proxy-pg creates schema on startup.
  Existing `tasks` and `task_updates` tables are NOT migrated. Fresh PG database
  required (or manual migration of data to `kv` table format).

### 7.3 Rollback Plan

If PR4 causes issues:
1. `helm rollback asya-gateway` restores old monolith deployment
2. Old `asya-gateway-api` and `asya-gateway-mesh` Deployments recreated
3. Actors still have `ASYA_GATEWAY_URL` env var (Crossplane not yet updated)
4. System functions as before

---

## 8. Cascade Checklist

Files to check when making these changes. Each line must be verified.

### Helm chart files to create:
- [ ] `deploy/helm-charts/asya-gateway/values.yaml` (full rewrite)
- [ ] `deploy/helm-charts/asya-gateway/templates/_helpers.tpl` (update helpers)
- [ ] `deploy/helm-charts/asya-gateway/templates/deployment.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/service-mesh-api.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/service-mesh-api-int.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/service-mcp.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/service-a2a.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/configmap.yaml` (rewrite)
- [ ] `deploy/helm-charts/asya-gateway/templates/configmap-mcp-tools.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/configmap-a2a-agents.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/secret.yaml` (simplify)
- [ ] `deploy/helm-charts/asya-gateway/templates/pdb.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/ingress-external-create.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/ingress-external-sticky.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/ingress-internal.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/networkpolicy.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/tests/test-mesh-api-health.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/tests/test-mesh-api-crud.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/templates/tests/test-mcp-adapter.yaml` (new)
- [ ] `deploy/helm-charts/asya-gateway/Chart.yaml` (update description)

### Helm chart files to delete:
- [ ] `deploy/helm-charts/asya-gateway/templates/deployment-api.yaml`
- [ ] `deploy/helm-charts/asya-gateway/templates/deployment-mesh.yaml`
- [ ] `deploy/helm-charts/asya-gateway/templates/service-api.yaml`
- [ ] `deploy/helm-charts/asya-gateway/templates/service-mesh.yaml`
- [ ] `deploy/helm-charts/asya-gateway/templates/db-migration-job.yaml`
- [ ] `deploy/helm-charts/asya-gateway/templates/configmap-flows.yaml`
- [ ] `deploy/helm-charts/asya-gateway/templates/rbac-flow-exposer.yaml`
- [ ] `deploy/helm-charts/asya-gateway/templates/tests/test-connection.yaml`
- [ ] `deploy/helm-charts/asya-gateway/templates/tests/test-db-schema.yaml`
- [ ] `deploy/helm-charts/asya-gateway/templates/tests/test-mcp-tools.yaml`

### Crossplane files to modify:
- [ ] `deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml`
- [ ] `deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml`
- [ ] `deploy/helm-charts/asya-crossplane/templates/composition-pubsub.yaml`
- [ ] `deploy/helm-charts/asya-crossplane/values.yaml`

### E2E test infrastructure to modify:
- [ ] `testing/e2e/charts/values.yaml`
- [ ] `testing/e2e/profiles/rabbitmq-minio.yaml`
- [ ] `testing/e2e/profiles/sqs-s3.yaml`
- [ ] `testing/e2e/profiles/pubsub-gcs.yaml`
- [ ] `testing/e2e/profiles/.env.rabbitmq-minio`
- [ ] `testing/e2e/profiles/.env.sqs-s3`
- [ ] `testing/e2e/profiles/.env.pubsub-gcs`
- [ ] `testing/e2e/scripts/deploy.sh`
- [ ] `testing/e2e/charts/helmfile.yaml.gotmpl`
- [ ] `testing/e2e/charts/flows.yaml` (may be removable)

### E2E test files to create:
- [ ] `testing/e2e/tests/test_mesh_api_e2e.py`
- [ ] `testing/e2e/tests/test_envelope_gateway_url_e2e.py`

### E2E test files to modify:
- [ ] `testing/e2e/tests/test_a2a_e2e.py`
- [ ] `testing/e2e/tests/test_gateway_routing_e2e.py`
- [ ] `testing/e2e/tests/conftest.py`

### Test helper files to modify:
- [ ] `src/asya-testing/asya_testing/fixtures/gateway.py`
- [ ] `src/asya-testing/asya_testing/config.py`
- [ ] `src/asya-testing/asya_testing/utils/gateway.py`

### Docker / build files to modify:
- [ ] `src/asya-gateway/Dockerfile` (multi-binary build)
- [ ] `src/build-images.sh` (add new image targets)
- [ ] `testing/e2e/scripts/deploy.sh` (load new images)

### Documentation to create/modify:
- [ ] `docs/setup/guide-gateway.md` (rewrite)
- [ ] `docs/usage/guide-gateway.md` (new or update)
- [ ] `docs/reference/env-vars.md` (deprecate ASYA_GATEWAY_URL)
- [ ] `docs/reference/components/core-sidecar.md` (update)
- [ ] `AGENTS.md` (update Gateway Routes section)

### Grep targets (ensure no stale references):
- `ASYA_GATEWAY_URL` — must only appear in: backward-compat fallback code
  (sidecar), Docker Compose test configs, deprecation notices
- `ASYA_GATEWAY_MODE` — must be removed entirely (no api/mesh modes anymore)
- `asya-gateway-api` — old service name, must be removed
- `asya-gateway-mesh` — old service name, must be removed
- `gatewayURL` — must be removed from Crossplane values and compositions
- `flowConfigMaps` — must be removed from gateway chart
- `exposedFlows` — must be removed from gateway chart
- `flow-exposer` — must be removed from gateway RBAC

### Build verification:
- [ ] `helm template deploy/helm-charts/asya-gateway/ -f <test-values>` renders without errors
- [ ] `helm template deploy/helm-charts/asya-crossplane/ -f <test-values>` renders without ASYA_GATEWAY_URL
- [ ] `make lint` passes
- [ ] `make test-unit` passes (Go + Python)
- [ ] `make build-images` builds all new images
- [ ] E2E: `make test-e2e PROFILE=rabbitmq-minio` passes full suite
