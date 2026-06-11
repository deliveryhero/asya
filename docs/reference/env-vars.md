---
description: "Environment variables: consolidated reference for all components (sidecar, runtime, gateway, mesh-api, mcp-adapter, a2a-adapter, crew, state proxy)"
---

# Environment Variables

Consolidated reference of all environment variables used by Asya components.
Grouped by component.

**Project policy**: environment variables must not have defaults in application
code. All required values are passed explicitly via Helm charts or Makefile
targets. The defaults listed below are what the code falls back to when a
variable is unset -- they exist for local development convenience, not for
production use.

---

## asya-sidecar

Source: `src/asya-sidecar/internal/config/config.go`

### Core

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_ACTOR_NAME` | Queue to consume from (logical actor name) | _(required)_ |
| `ASYA_NAMESPACE` | Kubernetes namespace (used for queue name prefix) | `""` |
| `ASYA_TRANSPORT` | Transport backend: `rabbitmq`, `sqs`, `pubsub` | `rabbitmq` |
| `ASYA_LOG_LEVEL` | Log level (`DEBUG`, `INFO`, `WARN`, `ERROR`) | _(unset)_ |

### Socket

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_SOCKET_DIR` | Directory for the runtime Unix socket | `/var/run/asya` |
| `ASYA_SOCKET_MESH_DIR` | Directory for mesh-mode sockets | `/var/run/asya/mesh` |

### Routing

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_ACTOR_SINK` | Success destination queue | `x-sink` |
| `ASYA_ACTOR_SUMP` | Error destination queue | `x-sump` |
| `ASYA_IS_END_ACTOR` | Disable response routing (for x-sink, x-sump) | `false` |

### Resiliency

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_RESILIENCY_ACTOR_TIMEOUT` | Per-call actor timeout (Go duration, e.g. `5m`, `30s`) | `5m` |
| `ASYA_RESILIENCY_POLICIES` | JSON object of named retry policies | `""` |
| `ASYA_RESILIENCY_RULES` | JSON array of error-to-policy matching rules | `""` |

### Gateway integration

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_GATEWAY_URL` | Gateway mesh URL for progress reporting | `""` |
| `ASYA_RUNTIME_READY_TIMEOUT` | Max wait for runtime to become ready | _(unset)_ |
| `ASYA_GATEWAY_READY_TIMEOUT` | Max wait for gateway to become reachable | _(unset)_ |

### Metrics

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_METRICS_ENABLED` | Enable Prometheus metrics | `true` |
| `ASYA_METRICS_ADDR` | Metrics server listen address | `:8080` |
| `ASYA_METRICS_NAMESPACE` | Prometheus metric name prefix | `asya_actor` |
| `ASYA_CUSTOM_METRICS` | JSON for custom Prometheus metrics | `""` |

### RabbitMQ transport

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_RABBITMQ_URL` | Full AMQP connection URL (overrides host/port/user/pass) | _(unset)_ |
| `ASYA_RABBITMQ_HOST` | RabbitMQ host | `localhost` |
| `ASYA_RABBITMQ_PORT` | RabbitMQ port | `5672` |
| `ASYA_RABBITMQ_USERNAME` | RabbitMQ username | `guest` |
| `ASYA_RABBITMQ_PASSWORD` | RabbitMQ password | `guest` |
| `ASYA_RABBITMQ_EXCHANGE` | RabbitMQ exchange name | `asya` |
| `ASYA_RABBITMQ_PREFETCH` | Prefetch count | `1` |
| `ASYA_QUEUE_RETRY_MAX_ATTEMPTS` | Max reconnection attempts on queue error | _(unset)_ |
| `ASYA_QUEUE_RETRY_BACKOFF` | Initial backoff duration for queue reconnection | _(unset)_ |

### SQS transport

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_SQS_ENDPOINT` | SQS endpoint URL (for LocalStack or custom endpoints) | `""` |
| `ASYA_AWS_REGION` | AWS region for SQS | `us-east-1` |
| `ASYA_SQS_VISIBILITY_TIMEOUT` | SQS visibility timeout (seconds) | `0` |
| `ASYA_SQS_WAIT_TIME_SECONDS` | SQS long-poll wait time (seconds) | `20` |

### Pub/Sub transport

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_PUBSUB_PROJECT_ID` | GCP project ID | `""` |
| `ASYA_PUBSUB_ENDPOINT` | Pub/Sub emulator endpoint | `""` |

---

## asya-runtime

Source: `src/asya-runtime/asya_runtime.py`

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_HANDLER` | Handler path (`module.function` or `module.Class.method`) | _(required)_ |
| `ASYA_SOCKET_DIR` | Socket directory | `/var/run/asya` |
| `ASYA_SOCKET_NAME` | Socket filename | `asya-runtime.sock` |
| `ASYA_SOCKET_CHMOD` | Socket file permissions (octal) | `0o666` |
| `ASYA_ENABLE_VALIDATION` | Validate incoming envelope structure | `true` |
| `ASYA_LOG_LEVEL` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `ASYA_PYTHONEXECUTABLE` | Python executable path (for non-standard installs) | _(unset)_ |
| `ASYA_STATE_PROXY_MOUNTS` | State proxy mount configuration (set by Crossplane) | _(unset)_ |

---

## asya-gateway

The gateway is no longer a single binary with an `ASYA_GATEWAY_MODE` switch. It is
split into separate containers, all built from the one `asya-gateway` image:

- **asya-mesh-api** — core HTTP server (see section below)
- **mcp-adapter** — MCP HTTP adapter (see section below)
- **a2a-adapter** — A2A JSON-RPC adapter (see section below)
- **state-proxy-mesh** — task/mesh state connector (`pg-kv` or `pvc-kv`, see below)

There is no shared `asya-gateway` env-var set; each container has its own. See the
[Gateway component reference](components/core-gateway.md) for the container split.

---

## asya-mesh-api

Source: `src/asya-gateway/cmd/mesh-api/main.go`

The mesh-api is a standalone HTTP server for the `/api/v1/mesh/` envelope API.
It exposes two ports: external (client-facing CRUD + SSE) and internal (sidecar
event publishing). Persistence is delegated to a pg-kv sidecar over
Unix socket.

### Core

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_MESH_EXTERNAL_PORT` | External API listen port | _(required)_ |
| `ASYA_MESH_INTERNAL_PORT` | Internal sidecar listen port | _(required)_ |
| `ASYA_STATEPROXY_SOCKET` | Unix socket path to the state-proxy (pg-kv or pvc-kv) | _(required)_ |
| `ASYA_INTERNAL_URL` | URL sidecars use for callbacks (stamped as `x-asya-gateway-url`) | _(required)_ |
| `ASYA_QUEUE_TRANSPORT` | Queue backend: `rabbitmq`, `sqs`, or `pubsub` | _(required)_ |
| `ASYA_NAMESPACE` | Kubernetes namespace for queue name prefix | `""` |
| `ASYA_MESH_API_PREFIX` | HTTP route prefix for mesh API (e.g. `/api/v1`, or `""` for unprefixed) | `/api/v1` |
| `ASYA_BACKSTOP_INTERVAL` | Poll cadence for the SLA backstop reaper (Go duration) | `5s` |
| `ASYA_LOG_LEVEL` | Log level | _(unset)_ |

### Transport (same as gateway)

Uses the same queue transport env vars as asya-gateway (`ASYA_QUEUE_TRANSPORT`,
`ASYA_RABBITMQ_URL`, `ASYA_SQS_ENDPOINT`, `ASYA_PUBSUB_PROJECT_ID`, etc.).

### Tracing

| Variable | Description | Default |
|----------|-------------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint. Format depends on protocol: gRPC → `host:4317`; HTTP → `http://host:4318` | _(unset)_ |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Transport protocol: `""` / `"grpc"` → gRPC (default); `"http"` → HTTP/protobuf | _(unset — gRPC)_ |

---

## state-proxy-mesh (pg-kv — default)

Source: `src/asya-state-proxy/go/cmd/pg-kv/main.go`

Default mesh state backend. Go-based PostgreSQL connector that runs as a sidecar
alongside asya-mesh-api, serving KV operations and Mango-style queries over a Unix
socket. Selected by `stateProxy.mesh.backend: pg-kv` in the gateway chart.

| Variable | Description | Default |
|----------|-------------|---------|
| `CONNECTOR_SOCKET` | Unix socket path | _(required)_ |
| `STATE_PROXY_PG_URL` | PostgreSQL connection string | _(required)_ |
| `STATE_PROXY_PG_INDEXES` | Comma-separated expression index specs (e.g. `status,(deadline_at)::timestamptz`) | `""` |

---

## state-proxy-mesh (pvc-kv — no PostgreSQL)

Source: `src/asya-state-proxy/go/cmd/pvc-kv/main.go`

Alternative mesh state backend that needs **no external database**. Stores task
state as JSON files on a PVC (or in memory) and queries them in-process with
DuckDB. Selected by `stateProxy.mesh.backend: pvc-kv` (requires `replicaCount: 1`).

| Variable | Description | Default |
|----------|-------------|---------|
| `CONNECTOR_SOCKET` | Unix socket path | _(required)_ |
| `PVC_KV_MODE` | Storage mode: `pvc` (files) or `inmem` (in-memory) | _(required)_ |
| `PVC_KV_BASE_DIR` | Storage root directory | _(required for `pvc` mode)_ |
| `PVC_KV_PARTITION` | `"true"` enables `active/` + `archive/` subdirs | `false` |
| `PVC_KV_ARCHIVE_STATUSES` | Comma-separated statuses to archive on delete | `""` |

---

## mcp-adapter

Source: `src/asya-gateway/cmd/mcp-adapter/main.go`

Standalone MCP Streamable HTTP adapter. Translates MCP `tools/list` and
`tools/call` into mesh-api HTTP calls using the two-step dispatch pattern.

| Variable | Description | Default |
|----------|-------------|---------|
| `MESH_API_URL` | Local mesh-api URL (same pod) for POST create / GET status | _(required)_ |
| `MESH_INGRESS_URL` | External Ingress URL for hash-routed SSE subscriptions | _(required)_ |
| `ASYA_MCP_CONFIG_DIR` | Directory containing tool definition YAML files (ConfigMap mount) | _(required)_ |
| `ASYA_MCP_PORT` | HTTP listen port | `8082` |
| `ASYA_MCP_POLL_INTERVAL` | ConfigMap polling interval for hot-reload | `10s` |
| `ASYA_LOG_LEVEL` | Log level (`DEBUG`, `INFO`, `WARN`, `ERROR`) | `INFO` |

---

## a2a-adapter

Source: `src/asya-gateway/cmd/a2a-adapter/main.go`

Standalone A2A JSON-RPC adapter. Implements A2A protocol over mesh-api
HTTP calls using the a2aproject/a2a-go v2 library.

| Variable | Description | Default |
|----------|-------------|---------|
| `MESH_API_URL` | Local mesh-api URL (same pod) for POST create / GET status | _(required)_ |
| `MESH_INGRESS_URL` | External Ingress URL for hash-routed SSE subscriptions | _(required)_ |
| `ASYA_A2A_CONFIG_DIR` | Directory containing agent definition YAML files (ConfigMap mount) | _(required)_ |
| `ASYA_A2A_PORT` | HTTP listen port | `8083` |
| `ASYA_A2A_POLL_INTERVAL` | ConfigMap polling interval for hot-reload | `10s` |
| `ASYA_A2A_NAME` | Agent card display name | `Asya Gateway` |
| `ASYA_A2A_DESCRIPTION` | Agent card description | `AI Actor Mesh for distributed agentic workloads` |
| `ASYA_A2A_VERSION` | Agent card version | `1.0.0` |
| `ASYA_A2A_PUBLIC_URL` | Public base URL for agent card | `""` |
| `ASYA_A2A_PROVIDER_ORG` | Agent card provider organization | `Asya` |
| `ASYA_A2A_PROVIDER_URL` | Agent card provider URL | `https://asya.sh` |
| `ASYA_LOG_LEVEL` | Log level (`DEBUG`, `INFO`, `WARN`, `ERROR`) | `INFO` |

---

## asya-crew

Source: `src/asya-crew/asya_crew/`

### Shared

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_PERSISTENCE_MOUNT` | Mount path for persisting envelopes | `""` |
| `ASYA_MSG_ROOT` | Root path for envelope message files | `/proc/asya/msg` |

### x-sink

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_SINK_HOOKS` | Comma-separated hook names to run on sink | `""` |
| `ASYA_SINK_FANOUT_HOOKS` | Run hooks for fan-out children | `false` |

### x-pause

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_PAUSE_METADATA` | Additional metadata to include in checkpoint | `""` |

### x-resume

| Variable | Description | Default |
|----------|-------------|---------|
| `ASYA_RESUME_MERGE_MODE` | How to merge resume input into payload: `shallow` | `shallow` |
