# ADR: ConfigMap-Based Flow Registry for Gateway Tool/Skill Exposure

**Status**: Accepted
**Date**: 2026-03-06
**Amended**: 2026-03-08 — polling chosen over fsnotify (see "Watcher implementation" below)
**Amended**: 2026-03-09 — per-flow data keys + server-side apply (see "Per-flow data keys and SSA" below)
**Context**: Gateway flow exposure design (brainstorming session)
**Supersedes**: `expose-flows-to-gateway/` epic (DB-backed `POST /mesh/expose` approach)
**Related**: A2A RFC section 8.4 (Registration API), section 13.4 (Tools Table)

---

## Decision

Exposed flows (MCP tools and A2A skills) are stored in a **Kubernetes ConfigMap**
(`gateway-flows`), not in PostgreSQL. The gateway reads the ConfigMap via a
mounted volume and watches for changes via polling. The write path goes through
`kubectl` (via `asya flow expose` CLI), which inherits K8s RBAC for free.

PostgreSQL remains solely for task execution state (status, progress, context).

---

## Context

### Problem

Data scientists need to expose compiled flows as MCP tools and A2A skills in the
gateway. The previous design used a DB-backed registry with `POST /mesh/expose`,
protected by an API key. This created two problems:

1. **RBAC gap**: A single API key is too coarse. Re-implementing K8s-like
   per-user authorization in the gateway is complex and fragile.
2. **Security constraint**: The gateway must not have K8s API access (no
   ServiceAccount with cluster permissions), ruling out TokenReview-based
   delegation.

### Trilemma

| Property | Description |
|---|---|
| Immediate consistency | All gateway replicas serve the same flow config |
| K8s RBAC for writes | No custom auth code in gateway |
| Gateway has no K8s API access | Security requirement |

Pick two. We drop immediate consistency (accept ~60s eventual consistency),
which gives us K8s RBAC and no K8s API access in the gateway.

---

## Architecture

```
DS laptop                        K8s API                    Gateway pod (xN)
   |                                |                            |
   | asya flow expose <flow>        |                            |
   |-- kubectl patch configmap ---->|                            |
   |   gateway-flows                |-- K8s RBAC check           |
   |<-- OK ------------------------|                            |
   |                                |-- kubelet sync (~60s) ---->|
   |                                |                            |-- polling watcher
   |                                |                            |-- reload YAML -> cache
```

### Data Separation

| Store | Data | Access pattern |
|---|---|---|
| ConfigMap (`gateway-flows`) | Flow definitions (routing, protocol metadata) | Read-only by gateway, written via kubectl |
| PostgreSQL | Task execution state (status, progress, SSE) | Read-write by gateway |

No overlap. No sync problem. A flow definition is only needed at task creation
time to resolve the entrypoint actor. After that, the task is self-contained in
PostgreSQL.

### ConfigMap Labels

The ConfigMap is addressed by label, not by name (K8s-native discovery):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-flows
  namespace: staging
  labels:
    asya.sh/component: gateway
    asya.sh/config-type: flows
data:
  flows.yaml: |
    flows: [...]
```

Gateway Helm chart mounts ConfigMaps matching label selector
`asya.sh/component=gateway,asya.sh/config-type=flows`.

### RBAC

K8s-native, zero gateway code:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: asya-flow-exposer
  namespace: staging
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    resourceNames: ["gateway-flows"]
    verbs: ["get", "patch", "update"]
```

---

## `flows.yaml` Schema

The original schema used a single `flows:` list in one data key. With the
per-flow data keys amendment (2026-03-09), each flow gets its own data key
in the ConfigMap. The gateway reads all `*.yaml` keys.

**Per-flow data key format** (one key per flow):
```yaml
# data key: extract-text.yaml
name: extract-text
entrypoint: text-extractor
description: "Extract text from PDF"
mcp:
  inputSchema:
    type: object
    properties:
      url: { type: string }
    required: [url]
```

**Original format** (single `flows.yaml` key with list — superseded):
```yaml
flows:
  - name: extract-text
    entrypoint: text-extractor
    description: "Extract text from PDF"
    mcp:
      inputSchema:
        type: object
        properties:
          url: { type: string }
        required: [url]

  # MCP tool + A2A skill
  - name: analyze-doc
    entrypoint: doc-analyzer
    description: "Analyze document themes"
    timeout: 300
    mcp:
      inputSchema:
        type: object
        properties:
          text: { type: string }
        required: [text]
    a2a:
      tags: [analysis, nlp]
      examples: ["Analyze this quarterly report for revenue trends"]

  # A2A skill only
  - name: research-assistant
    entrypoint: research-agent
    description: "Research any topic and provide a summary"
    a2a:
      tags: [research, general]
      examples: ["What are the latest trends in renewable energy?"]
      input_modes: [text/plain, application/json]
      output_modes: [text/plain]
```

### Field Reference

| Field | Required | Description |
|---|---|---|
| `name` | yes | Flow identifier. MCP tool name and A2A skill `id`. |
| `entrypoint` | yes | Actor name. Gateway resolves to queue `asya-{ns}-{actor}`. |
| `description` | yes | Human-readable. Shared by MCP and A2A. |
| `timeout` | no | E2E flow execution timeout (seconds). Null = gateway default. |
| `mcp` | no | Present = exposed as MCP tool in `tools/list`. |
| `mcp.inputSchema` | no | JSON Schema Draft 7. Passed to MCP `tools/list` as `inputSchema`. |
| `a2a` | no | Present = exposed as A2A skill in Agent Card. |
| `a2a.tags` | yes (if a2a) | Skill tags for discoverability (A2A spec: required). |
| `a2a.examples` | no | Example prompts for the skill. |
| `a2a.input_modes` | no | MIME types. Default: `[application/json]`. |
| `a2a.output_modes` | no | MIME types. Default: `[application/json]`. |

### Protocol Exposure Rule

- `mcp:` present = MCP tool
- `a2a:` present = A2A skill in Agent Card
- Both = both
- Neither = validation error (flow must be exposed via at least one protocol)

### Mapping to Internal Types

| YAML field | Gateway internal | MCP | A2A AgentSkill |
|---|---|---|---|
| `name` | `Name` | tool name | `id` |
| `description` | `Description` | tool description | `description` |
| `mcp.inputSchema` | `InputSchema` | `inputSchema` | not used |
| `timeout` | `TimeoutSec` | gateway-level | gateway-level |
| `a2a.tags` | `A2ATags` | not used | `tags` |
| `a2a.examples` | `A2AExamples` | not used | `examples` |
| `a2a.input_modes` | `A2AInputModes` | not used | `input_modes` |
| `a2a.output_modes` | `A2AOutputModes` | not used | `output_modes` |

---

## `asya k expose` CLI

**Amendment (2026-03-09)**: Command renamed from `asya flow expose` to
`asya k expose` per the k/d command split (see `adr.k-d-command-split.md`).

Restricted to flows only. Single actors must first be compiled to a single-actor
flow (see aint `[zmuh]`).

### Mechanics

1. Find entrypoint from compiled manifests in `base/` (label
   `asya.sh/flow-role=entrypoint`). No K8s API call needed.
2. Generate `configmap-flows.yaml` ConfigMap manifest with per-flow data key
3. Write to `.asya/manifests/<flow>/base/configmap-flows.yaml`
4. Update `base/kustomization.yaml` resources list
5. On next `asya k deploy`, applied via `kubectl apply --server-side`
   with `--field-manager=asya-flow-<name>` (K8s RBAC validates)

### CLI Flags

```bash
# MCP tool (--mcp is default if neither --mcp nor --a2a specified)
asya k expose order-processing \
  --description "Process orders" \
  --input-schema-file schema.json

# A2A skill
asya k expose research-assistant \
  --description "Research any topic" \
  --a2a --tags research,general \
  --examples "What are trends in renewable energy?"

# Both protocols
asya k expose analyze-doc \
  --description "Analyze document themes" \
  --mcp --input-schema-file schema.json \
  --a2a --tags analysis,nlp
```

| Flag | Protocol | Description |
|------|----------|-------------|
| `--description` | shared | Flow description (required) |
| `--timeout` | shared | E2E timeout in seconds |
| `--mcp` | MCP | Enable MCP tool exposure (default) |
| `--input-schema` | MCP | JSON Schema inline |
| `--input-schema-file` | MCP | JSON Schema from file |
| `--a2a` | A2A | Enable A2A skill exposure |
| `--tags` | A2A | Comma-separated tags |
| `--examples` | A2A | Example prompts (repeatable) |
| `--input-modes` | A2A | MIME types (default: application/json) |
| `--output-modes` | A2A | MIME types (default: application/json) |

### Generated ConfigMap Manifest

```yaml
# .asya/manifests/order-processing/base/configmap-flows.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-flows
  labels:
    asya.sh/component: gateway
    asya.sh/config-type: flows
data:
  order-processing.yaml: |
    name: order-processing
    entrypoint: start-order-processing
    description: "Process an order end-to-end"
    mcp:
      inputSchema:
        type: object
        properties:
          order_id: { type: string }
        required: [order_id]
```

### Removal

```bash
asya k unexpose order-processing
# + removes base/configmap-flows.yaml
# + kubectl patch configmap gateway-flows --type=json \
#     -p '[{"op":"remove","path":"/data/order-processing.yaml"}]'
```

---

## Gateway Changes

### Watcher implementation

**Amendment (2026-03-08)**: The original design specified a watcher using
`inotify`/`fsnotify`. After implementation, **polling was chosen instead**.

Kubernetes ConfigMap volume mounts do not use in-place file writes. When kubelet
syncs a ConfigMap it performs an **atomic symlink swap**:

```
/etc/asya/flows/
  flows.yaml  →  ..data/flows.yaml           (symlink)
  ..data      →  ..2026_03_08_10_00_00.xyz/  (symlink, atomically replaced)
```

`inotify` watches inodes. The symlink swap fires `IN_DELETE`+`IN_CREATE` on
`..data`, not `IN_MODIFY` on `flows.yaml`. Correctly tracking this requires
watching the parent directory and following the symlink chain — significant extra
complexity, and a known source of bugs in projects using `fsnotify` with
ConfigMap mounts (e.g. `controller-runtime` certwatcher).

`os.ReadDir` + `stat` naturally follow symlinks on every call, making polling
immune to this problem. Cost is ~3 syscalls per interval, all served from the
kernel's dentry cache (no disk I/O). At the default 10 s interval this is
negligible — and there is no point reacting faster than kubelet's own sync
period (~60 s default).

Poll interval is configurable via `ASYA_CONFIG_POLL_INTERVAL` (Go duration
string, e.g. `"10s"`, `"30s"`). Default: `10s`.

### Per-flow data keys and SSA

**Amendment (2026-03-09)**: The original design used a single `data.flows.yaml`
key with a list of all flows. This is replaced by **per-flow data keys** — each
flow gets its own key in the ConfigMap (e.g., `data.order-processing.yaml`).

**Rationale**: Each flow's `configmap-flows.yaml` is a K8s ConfigMap manifest
in the flow's `base/` directory (three-layer kustomize structure, see asya-lab
RFC section 8.1). Multiple flows deploy independently via `kubectl apply
--server-side --field-manager=asya-flow-<name>`. Per-flow data keys + SSA
field managers ensure no conflicts — each flow's field manager owns only its
data key. No patching ceremony, no merge conflicts.

**Gateway change**: Read all `*.yaml` keys from the ConfigMap data (not just
`flows.yaml`). Each key contains a single flow entry. Trivial change (~5 LOC):
iterate `data` map instead of parsing `flows:` list from one key.

**GitOps**: ArgoCD and FluxCD must be configured for server-side apply:
- ArgoCD: `syncOptions: [ServerSideApply=true]`
- FluxCD: `spec.serverSideApply: true`

Without SSA, client-side apply would wipe other flows' data keys.

### What Changes

- `toolstore.Registry` reads from YAML files instead of PostgreSQL
- Polling watcher on mounted config directory (`toolstore.Watch`, ~40 LOC); FNV-64a hash of name+mtime+size detects changes
- Reload YAML into in-memory atomic cache on fingerprint change
- Registry reads all `*.yaml` data keys from ConfigMap (each key = one flow entry)
- Remove `tools` DB table and migration
- `POST /mesh/expose` removed (write path is kubectl/SSA)
- `GET /mesh/expose` removed (not served by any mode; mesh pod has no registry)
- Agent Card regenerated on each reload from `a2a:`-enabled flows

### What Stays Unchanged

- `Registry` interface: `All()`, `GetByName()`, `MCPTools()`, `A2ASkills()`
- In-memory atomic cache pattern (`atomic.Value`)
- MCP server, A2A handler, task store, queue client
- PostgreSQL for task state

---

## Pros

1. **K8s RBAC for free** -- no custom auth code in gateway. Platform engineers
   control access with standard Roles and RoleBindings.
2. **Gateway stays K8s-unaware** -- no ServiceAccount permissions, no API access,
   no informers. Reads mounted files only.
3. **Simple implementation** -- polling watcher is ~40 LOC. YAML loader is ~50 LOC.
   No DB migrations, no HTTP write handlers, no auth middleware.
4. **GitOps compatible** -- ConfigMap YAML can be stored in git, applied by
   ArgoCD/FluxCD. Full audit trail via git history.
5. **No shadow control plane** -- the gateway doesn't become a second API server
   with its own RBAC. K8s remains the single source of truth for authorization.
6. **Horizontal scaling works naturally** -- kubelet syncs ConfigMap to all pods.
   No DB connection pool sizing for reads.

## Cons

1. **~60s eventual consistency** -- kubelet syncs ConfigMap to pods periodically.
   During this window, replicas may disagree on which flows are available.
2. **ConfigMap size limit** -- 1 MiB per ConfigMap. Each flow entry is ~200-500
   bytes, so ~2000-5000 flows per ConfigMap. Sufficient for foreseeable use, but
   a hard ceiling.
3. **No audit trail in gateway** -- no `created_at`/`updated_at` timestamps in
   the gateway. Audit trail lives in git (if GitOps) or `kubectl` audit logs.
4. **kubectl dependency** -- data scientists must have `kubectl` access (via
   `asya-lab` CLI wrapper). Pure HTTP clients cannot register flows.

## Risks

1. **Kubelet sync delay under load** -- under heavy node pressure, kubelet
   ConfigMap sync may exceed 60s. In extreme cases, replicas could serve stale
   config for minutes. Mitigation: monitor kubelet sync latency; gateway logs
   reload events with timestamps.
2. **ConfigMap corruption** -- a malformed `kubectl patch` could break all flows
   for all replicas. Mitigation: gateway validates YAML on reload; if invalid,
   keeps previous valid config and logs error.
3. **Race on concurrent deploys** -- two `asya k deploy` calls applying the
   ConfigMap simultaneously could conflict. Mitigation: server-side apply uses
   per-flow field managers (`asya-flow-<name>`), so concurrent deploys of
   different flows never conflict. Same-flow concurrent deploys use K8s
   resource versioning (optimistic concurrency).
4. **GitOps tools must use SSA** -- ArgoCD/FluxCD default to client-side apply,
   which would wipe other flows' data keys. Mitigation: document SSA
   configuration requirement (`syncOptions: [ServerSideApply=true]` for ArgoCD,
   `spec.serverSideApply: true` for FluxCD).
5. **ConfigMap size creep** -- large `inputSchema` definitions could push toward
   the 1 MiB limit. Mitigation: warn in CLI when ConfigMap exceeds 500 KiB.

## Limitations

1. **No per-flow access control** -- K8s RBAC grants access to the entire
   ConfigMap, not individual flow entries. Any user with ConfigMap patch access
   can modify any flow. Fine-grained per-flow ACLs would need a custom admission
   webhook.
2. **No programmatic HTTP write path** -- external systems (CI/CD pipelines,
   notebooks without kubectl) cannot register flows via HTTP. They must use
   `kubectl` or the `asya-lab` SDK (which wraps kubectl).
3. **No cross-namespace flow discovery** -- each gateway serves one namespace.
   Flows in other namespaces are invisible. Cross-namespace discovery requires
   a federation layer (out of scope).
4. **Eventual consistency affects `ListTools`/`ListSkills`** -- a client may
   list tools on replica A (sees new flow), then call the tool and hit replica B
   (which hasn't synced yet, returns 404). Standard eventual consistency race,
   acceptable for deploy-time operations.
5. **No real-time flow health** -- the ConfigMap records that a flow exists, not
   that its actors are healthy. A flow can be "exposed" but its actors may be
   scaled to zero or failing. Health checks are out of scope for this design.

---

## Impact on A2A RFC

The following sections of the A2A RFC (`rfc.md`) are affected:

- **Section 8.4 (Registration API)**: `POST /mesh/expose` is superseded by
  ConfigMap-based registration. `GET /mesh/expose` remains as read-only.
- **Section 13.4 (Tools Table)**: The `tools` PostgreSQL table is superseded by
  the `gateway-flows` ConfigMap. No DB migration needed for tools.
- **Section 8.1 (Agent Card)**: Agent Card refresh trigger changes from
  POST/DELETE on `/mesh/expose` to polling-detected ConfigMap changes.

See patch notes in `rfc.md` for details.

---

## Documentation

After implementation, the YAML schema and behavior must be documented in
`docs/usage/flow-expose.md`, covering:

- Per-flow data key schema reference with examples
- `asya k expose` / `asya k unexpose` CLI usage
- `configmap-flows.yaml` manifest format
- RBAC setup for platform engineers
- Eventual consistency behavior and expectations
- ConfigMap size limits and monitoring
- Server-side apply requirement (asya CLI, ArgoCD, FluxCD configuration)
- Three-layer kustomize structure (`base/configmap-flows.yaml`, overlay `$patch: delete`)
- Troubleshooting (stale config, validation errors, SSA field manager conflicts)

---

## Related Aints

- `[zmuh]` -- Flow compiler: support single-actor flows without start router
- `[1fiy]` -- Add fsnotify file watcher to asya-gateway (resolved: polling used instead)
- `[1f9j]` -- Implement `asya flow deploy`/`undeploy`/`expose` CLI commands
