---
title: Review all docs against Diataxis framework
priority: 2 # medium
assignee: Artem Yushkovskiy
---



Audit completed. Initial Diataxis phases 1-4 executed in PR #338 (split oversized docs,
write tutorials, fill gaps, polish). The restructure design below supersedes those phases
with a comprehensive audience-driven reorganization.

---

# Docs Restructure Design

**Date**: 2026-03-20
**Aint**: u1zh (audit), zb3d/ugr8/d2pn/w91z (implementation phases)
**Status**: Approved

## Problem

The `docs/` directory has grown organically and suffers from:

1. **Mixed concerns** — documentation content lives alongside website assets (stylesheets, images, mkdocs config)
2. **Directory proliferation** — 15 directories with overlapping scopes (internal vs reference, tutorials vs quickstart, howto vs operate vs install)
3. **No audience awareness** — docs don't reflect the two primary audiences: actor authors (data scientists) and platform engineers
4. **Missing concepts** — key ideas from the Asya KubeCon presentation (actor mesh, envelope mutation, sync gateway, timeouts, streaming) lack dedicated documentation

## Design Principles

1. **Two paths, one tree** — actor authors and platform engineers enter from different landing pages (`usage/`, `setup/`) but share `reference/` and top-level concept docs. No explicit "for data scientists" / "for engineers" labels — the scope naturally attracts the right audience.
2. **Flat with prefixes** — within `usage/` and `setup/`, files use prefixes (`start-`, `guide-`, `ops-`) for lexical grouping instead of subdirectories. READMEs provide the reading order.
3. **Mirrored concepts** — concepts that span both audiences (actor-flavors, state, pause-resume, timeouts) exist in both `usage/` and `setup/` with the same filename and cross-links. Usage answers "how do I use this?", setup answers "how do I provision this?"
4. **Separate website from content** — `docs/` is pure documentation. Website config (mkdocs, stylesheets, images, JS) moves to `docs/website/`.
5. **Reference is strict technical information** — component specs, protocol specs, CRD reference, env vars. Shared by both audiences.

## Target Structure

```
docs/
  README.md                         Landing page with code teasers + two depth paths
  concepts.md                       Actor mesh, envelope protocol, two-file model, independent scaling
  motivation.md                     Why choreography, when to use Asya, when not to
  architecture.md                   High-level system overview, sync gateway, component map

  reference/
    components/
      README.md                     Index: core (runtime infra) vs lab (developer tooling)
      core-sidecar.md               Sidecar message routing, transport interface, config, resiliency internals
      core-runtime.md               Handler loading, async support, response patterns
      core-gateway.md               Gateway modes, API routes, state management, auth schemes
      core-crew.md                  System actors (x-sink, x-sump, x-pause, x-resume), checkpointer internals
      core-crossplane.md            XRD schema, composition pipeline, status model
      core-state-proxy.md           State proxy architecture, connectors, limitations
      core-actor.md                 AsyncActor resource behavior, label propagation
      lab-flow-compiler.md          Compiler internals, CPS transformation, IR
      lab-cli.md                    CLI reference — asya flow, mcp, build, k
      lab-sdk.md                    (planned) Python SDK for actor development
      lab-vscode.md                 (planned) VS Code extension
      lab-jupyter.md                (planned) JupyterLab magic commands
    specs/
      README.md                     Index: protocols, interfaces, and formal specifications
      envelope.md                   Envelope structure, queue naming, routing logic
      sidecar-runtime.md            HTTP endpoints, error codes, timeout strategy
      gateway-api.md                Full HTTP API reference (A2A, MCP, mesh, OAuth)
      abi-protocol.md               ABI yield forms (GET, SET, DEL, FLY)
      flow-dsl.md                   Flow DSL syntax, supported constructs, compilation rules
      error-handling.md             Error routing spec (policy exhaustion, DLQ, x-sump)
      asyncactor-crd.md             Full CRD field reference from XRD
    transports/                     Pluggable message transports
      README.md                     Transport abstraction, interface, comparison, selection
      sqs.md                        SQS config, IAM, DLQ, KEDA, cost
      rabbitmq.md                   RabbitMQ config, auth, DLQ, KEDA
      pubsub.md                     GCP Pub/Sub config, service accounts, DLQ, KEDA
      socket.md                     Socket transport (local testing), wire protocol
    connectors/                     Pluggable state-proxy storage backends
      README.md                     Connector abstraction, interface, comparison, selection
      s3.md                         S3/MinIO config, IAM, key patterns
      gcs.md                        GCS config, service accounts, key patterns
      redis.md                      Redis config, LWW vs CAS, connection pooling
      nats-kv.md                    NATS KV config, JetStream setup
    README.md                       Index: what's in components/, specs/, transports/
    env-vars.md                     Consolidated env vars across all components (cross-cutting)

  usage/                            Actor authors: write, compose, debug
    README.md                       "Start building" entry point, section guide
    start-first-actor.md            Build an echo actor, deploy, send message, verify
    start-first-actor-mesh.md       Chain two actors via route.next, trace envelope at each hop
    start-first-flow.md             Write Flow DSL, compile, inspect routers, deploy
    guide-handler-patterns.md       Adapter pattern, generator vs function, typed outputs
    guide-agentic-patterns.md       Fan-out, dynamic routing, conditional branching
    guide-streaming.md              FLY events, SSE, live progress to gateway clients
    guide-actor-flavors.md          Choose and use flavors in actor specs (cross-links setup/)
    guide-state-proxy.md            Read/write /state/ paths in handlers (cross-links setup/)
    guide-pause-resume.md           Yield SET to x-pause, handle resume input (cross-links setup/)
    guide-timeouts.md               Set actorTimeout in spec, understand deadline behavior (cross-links setup/)
    ops-debugging.md                Trace envelopes by trace_id, curl runtime, check x-sink/x-sump

  setup/                            Platform engineers: deploy, configure, operate
    README.md                       "Run Asya" entry point, section guide
    start-quickstart.md             Local Kind cluster in 5 minutes
    start-aws-eks.md                Production EKS deployment
    start-gcp-gke.md                Production GKE deployment
    guide-helm-charts.md            Chart configuration reference (gateway, crew, crossplane)
    guide-autoscaling.md            KEDA configuration, scaling parameters, scenarios
    guide-actor-flavors.md          Create EnvironmentConfig resources for your org (cross-links usage/)
    guide-state-proxy.md            Configure state-proxy storage backends (cross-links usage/)
    guide-pause-resume.md           Deploy x-pause/x-resume crew, configure S3 checkpoint (cross-links usage/)
    guide-timeouts.md               Configure SLA, gateway backstop, transport timeouts (cross-links usage/)
    guide-retries.md                Retry policies, error matching, DLQ configuration
    guide-gateway.md                Deploy gateway modes, configure auth, tool registration
    ops-monitoring.md               Prometheus metrics, Grafana dashboards, alerting
    ops-troubleshooting.md          Symptom-to-solution checklist
    ops-upgrades.md                 Version upgrade procedures, rollback

  contributing/                     Contributors only (test strategy)
    README.md                       Scope and index
    testing-a2a.md                  A2A protocol test strategy across all levels
    testing-state-proxy.md          State proxy / storage backend test strategy
    testing-transport.md            Transport backend test strategy

docs/website/                       MkDocs / asya.sh site config (separate from content)
  mkdocs.yml                        Site config (moved from repo root)
  stylesheets/                      extra.css, shared.css (moved from docs/stylesheets/)
  img/                              Logos, diagrams (moved from docs/img/)
  js/                               search-bridge.js
  requirements.txt                  MkDocs dependencies (moved from docs/mkdocs/)
```

### Files removed from docs/

| Current location | Action |
|------------------|--------|
| `docs/stylesheets/` | Move to `docs/website/stylesheets/` |
| `docs/img/` (static assets) | Move logos, PNGs, SVGs to `docs/website/img/` |
| `docs/img/flows/` (code artifacts) | Move to `examples/flows/compiled/` — these are compiled flow examples (Python, dot, SVG), not website assets |
| `docs/mkdocs/` | Move to `docs/website/` (requirements.txt, README) |
| `mkdocs.yml` (repo root) | Move to `docs/website/mkdocs.yml`, update `docs_dir` to `../docs` |
| `docs/plans/` | Add to `.gitignore`, add note to AGENTS.md to never commit |
| `docs/comparisons/` | Delete `.venv/` dirs (hundreds of MBs, not docs). Keep comparison scripts if any exist outside `.venv/`, move to `.aint/aints/` as research artifacts. Add `docs/comparisons/` to `.gitignore`. |
| `docs/internal/` | Rename to `docs/contributing/`, move reference-worthy files out |
| `docs/architecture/` | Dissolves: README.md becomes top-level `architecture.md`, component files move to `reference/components/`, protocols to `reference/specs/`, transports to `reference/transports/` |
| `docs/features/` | Dissolves: resiliency content splits to `reference/` + `setup/guide-retries.md`, task-pause splits to `usage/guide-pause-resume.md` + `setup/guide-pause-resume.md` |
| `docs/explanation/` | Dissolves: content merges into `concepts.md`, `architecture.md`, or relevant usage/setup guides |
| `docs/howto/` | Dissolves: content moves to `usage/` or `setup/` guides |
| `docs/tutorials/` | Dissolves: content moves to `usage/` (start- and guide- files) |
| `docs/quickstart/` | Dissolves: README.md becomes `setup/start-quickstart.md`, usage.md content distributes to `usage/` |
| `docs/install/` | Dissolves: files become `setup/start-*.md` and `setup/guide-helm-charts.md` |
| `docs/operate/` | Dissolves: files become `setup/ops-*.md` |
| `docs/reference/` | Survives but reorganized: gains `components/`, `specs/`, `transports/` subdirs |

### Mirrored concept pairs

4 files exist in both `usage/` and `setup/` with the same name and cross-links:

| Filename | usage/ scope | setup/ scope |
|----------|-------------|--------------|
| `guide-actor-flavors.md` | Choose flavors in actor spec | Create EnvironmentConfig resources |
| `guide-state-proxy.md` | Read/write `/state/` paths in handlers | Configure storage backends (S3, GCS, Redis) |
| `guide-pause-resume.md` | Yield SET to x-pause, handle resume | Deploy crew actors, configure S3 checkpoint |
| `guide-timeouts.md` | Set actorTimeout, understand deadlines | Configure SLA, gateway backstop, transport timeouts |

Cross-link pattern at the bottom of each mirrored file:

```markdown
---
**Platform setup**: To configure [concept] infrastructure, see [setup/guide-concept.md](../setup/guide-concept.md).
```

```markdown
---
**Using [concept]**: To use [concept] in your actor handlers, see [usage/guide-concept.md](../usage/guide-concept.md).
```

### Landing page (docs/README.md)

Two code teasers — no mention of audience categories, just scope:

```markdown
## Build AI Actors

```python
def handler(payload):
    result = my_model.predict(payload["input"])
    return {"prediction": result}
```

Write a Python function, deploy as a Kubernetes actor, chain into pipelines.
[Start building](usage/README.md)

## Run the Platform

```yaml
apiVersion: async.asya.sh/v1alpha1
kind: AsyncActor
spec:
  handler: my_handler.py
  scaling:
    queueLength: 5
```

Deploy Asya on your cluster, configure transports, monitor and scale.
[Set up Asya](setup/README.md)

### Content migration map

| Source file | Destination |
|------------|-------------|
| `docs/README.md` | `docs/README.md` (rewrite with teasers) |
| `docs/concepts.md` | `docs/concepts.md` (expand with actor mesh, envelope mutation, two-file model) |
| `docs/motivation.md` | `docs/motivation.md` (keep) |
| `docs/architecture/README.md` | `docs/architecture.md` (promote to top-level, expand with sync gateway) |
| `docs/architecture/asya-sidecar.md` | `docs/reference/components/core-sidecar.md` |
| `docs/architecture/asya-runtime.md` | `docs/reference/components/core-runtime.md` |
| `docs/architecture/asya-gateway.md` | `docs/reference/components/core-gateway.md` |
| `docs/architecture/asya-crew.md` | `docs/reference/components/core-crew.md` |
| `docs/architecture/asya-crossplane.md` | `docs/reference/components/core-crossplane.md` |
| `docs/architecture/asya-state-proxy.md` | `docs/reference/components/core-state-proxy.md` |
| `docs/architecture/asya-actor.md` | `docs/reference/components/core-actor.md` |
| `docs/architecture/asya-flow.md` | `docs/reference/components/lab-flow-compiler.md` |
| `docs/architecture/asya-lab.md` | Remove (already redirect stub to reference/cli.md) |
| `docs/architecture/autoscaling.md` | Remove (already redirect stub to howto/configure-autoscaling.md) |
| `docs/architecture/observability.md` | `docs/setup/ops-monitoring.md` (merge with operate/monitoring.md) |
| `docs/architecture/protocols/actor-actor.md` | `docs/reference/specs/envelope.md` |
| `docs/architecture/protocols/sidecar-runtime.md` | `docs/reference/specs/sidecar-runtime.md` |
| `docs/architecture/transports/README.md` | `docs/reference/transports/README.md` |
| `docs/architecture/transports/sqs.md` | `docs/reference/transports/sqs.md` |
| `docs/architecture/transports/rabbitmq.md` | `docs/reference/transports/rabbitmq.md` |
| `docs/architecture/transports/socket.md` | `docs/reference/transports/socket.md` |
| `docs/features/resiliency.md` | Policy tables → section in `docs/reference/components/core-sidecar.md`; recipes → `docs/setup/guide-retries.md` |
| `docs/features/task-pause.md` | `docs/usage/guide-pause-resume.md` + `docs/setup/guide-pause-resume.md` |
| `docs/explanation/flow-compilation.md` | Merge into `docs/reference/components/flow-compiler.md` |
| `docs/explanation/agentic-design.md` | Merge into `docs/usage/guide-agentic-patterns.md` |
| `docs/explanation/choreography-vs-orchestration.md` | Merge into `docs/motivation.md` or `docs/concepts.md` |
| `docs/explanation/envelope-design.md` | Merge into `docs/concepts.md` |
| `docs/howto/configure-retries.md` | `docs/setup/guide-retries.md` |
| `docs/howto/configure-autoscaling.md` | `docs/setup/guide-autoscaling.md` |
| `docs/howto/setup-pause-resume.md` | `docs/setup/guide-pause-resume.md` |
| `docs/howto/add-new-actor.md` | `docs/usage/guide-handler-patterns.md` (merge) |
| `docs/howto/debug-envelope.md` | `docs/usage/ops-debugging.md` |
| `docs/howto/register-gateway-tools.md` | `docs/setup/guide-gateway.md` |
| `docs/reference/abi-protocol.md` | `docs/reference/specs/abi-protocol.md` |
| `docs/reference/flow-dsl.md` | `docs/reference/specs/flow-dsl.md` |
| `docs/reference/asyncactor-crd.md` | `docs/reference/specs/asyncactor-crd.md` |
| `docs/reference/env-vars.md` | `docs/reference/env-vars.md` (keep) |
| `docs/reference/cli.md` | `docs/reference/components/lab-cli.md` |
| `docs/reference/agentic-cheatsheet.md` | Merge into `docs/usage/guide-agentic-patterns.md` |
| `docs/tutorials/first-actor.md` | `docs/usage/start-first-actor.md` |
| `docs/tutorials/first-pipeline.md` | `docs/usage/start-first-actor-mesh.md` |
| `docs/tutorials/first-flow.md` | `docs/usage/start-first-flow.md` |
| `docs/tutorials/pause-resume.md` | `docs/usage/guide-pause-resume.md` (merge) |
| `docs/tutorials/agentic-patterns.md` | `docs/usage/guide-agentic-patterns.md` |
| `docs/tutorials/actor-handler-adapter-pattern.md` | `docs/usage/guide-handler-patterns.md` |
| `docs/tutorials/actor-flavors.md` | `docs/usage/guide-actor-flavors.md` |
| `docs/quickstart/README.md` | `docs/setup/start-quickstart.md` |
| `docs/quickstart/usage.md` | Content distributes to `docs/usage/` start- files |
| `docs/install/aws-eks.md` | `docs/setup/start-aws-eks.md` |
| `docs/install/gcp-gke.md` | `docs/setup/start-gcp-gke.md` |
| `docs/install/local-kind.md` | `docs/setup/start-quickstart.md` (merge with quickstart) |
| `docs/install/helm-charts.md` | `docs/setup/guide-helm-charts.md` |
| `docs/operate/monitoring.md` | `docs/setup/ops-monitoring.md` |
| `docs/operate/scaling.md` | Remove (already redirect stub) |
| `docs/operate/troubleshooting.md` | `docs/setup/ops-troubleshooting.md` |
| `docs/operate/upgrades.md` | `docs/setup/ops-upgrades.md` |
| `docs/internal/README.md` | `docs/contributing/README.md` |
| `docs/internal/actor-flavors.md` | `docs/reference/components/actor.md` (merge) |
| `docs/internal/crew-checkpointer.md` | Key format/schema → section in `docs/reference/components/core-crew.md`; user-facing config → `docs/setup/guide-pause-resume.md` |
| `docs/internal/crew-termination.md` | `docs/reference/specs/error-handling.md` |
| `docs/internal/gateway-api-spec.md` | `docs/reference/specs/gateway-api.md` |
| `docs/internal/gateway-security.md` | Auth schemes → section in `docs/reference/components/core-gateway.md`; setup steps → `docs/setup/guide-gateway.md` |
| `docs/internal/resiliency.md` | Internals (policy matching, delay computation) → section in `docs/reference/components/core-sidecar.md` |
| `docs/internal/testing-a2a.md` | `docs/contributing/testing-a2a.md` |
| `docs/internal/testing-state-proxy.md` | `docs/contributing/testing-state-proxy.md` |
| `docs/internal/testing-transport.md` | `docs/contributing/testing-transport.md` |

### New content to write

| File | Content | Source |
|------|---------|--------|
| `docs/concepts.md` additions | Actor mesh pattern, envelope mutation, two-file model, independent scaling | KubeCon presentation, existing motivation.md |
| `docs/architecture.md` additions | Sync gateway explanation, component interaction map | KubeCon presentation, existing architecture/README.md |
| `docs/usage/guide-streaming.md` | FLY events, SSE, live progress to clients | Existing ABI docs + agentic-patterns.md |
| `docs/usage/guide-timeouts.md` | Setting actorTimeout, understanding deadline behavior | Existing sidecar/runtime docs |
| `docs/usage/guide-state-proxy.md` | Using /state/ paths in handlers, LWW vs CAS | Existing state-proxy docs |
| `docs/setup/guide-timeouts.md` | SLA config, gateway backstop, transport timeouts | Existing sidecar/gateway docs |
| `docs/setup/guide-state-proxy.md` | Configure storage backends (S3, GCS, Redis, NATS KV) | Existing state-proxy docs |
| `docs/setup/guide-gateway.md` | Deploy modes, auth config, tool registration | Existing gateway docs + howto/register-gateway-tools.md |
| `docs/reference/transports/pubsub.md` | GCP Pub/Sub transport config, service accounts, DLQ, KEDA | Existing GKE install guide + source code |
| `docs/reference/connectors/README.md` | Connector abstraction, interface, comparison, selection | Existing state-proxy docs + source code |
| `docs/reference/connectors/s3.md` | S3/MinIO state connector config | Existing state-proxy docs + source code |
| `docs/reference/connectors/gcs.md` | GCS state connector config | Source code |
| `docs/reference/connectors/redis.md` | Redis state connector config, LWW vs CAS | Source code |
| `docs/reference/connectors/nats-kv.md` | NATS KV state connector config | Source code |

### docs/website/ setup

```
docs/website/
  mkdocs.yml                Updated: docs_dir: ../docs, nav reflects new structure
  stylesheets/              Moved from docs/stylesheets/
    extra.css
    shared.css
  img/                      Moved from docs/img/
    (all images)
  js/
    search-bridge.js
  requirements.txt          Moved from docs/mkdocs/requirements.txt
  README.md                 Moved from docs/mkdocs/README-mkdocs-shadcn-patch.md
```

**Image path strategy**: Use mkdocs `custom_dir` overlay so that `docs/website/img/` is served
at the `/img/` URL path. Docs continue to reference images as `../docs/website/img/foo.png`
from markdown, but mkdocs sees them at `/img/foo.png` via the overlay. This must be prototyped
and tested before the migration begins.

**mkdocs.yml configuration**: The moved `mkdocs.yml` needs:
- `docs_dir: ..` to find content (docs/website/ → docs/)
- `custom_dir: .` or explicit overlay for stylesheets/img/js
- Updated `extra_css`, `extra_javascript` paths
- Full `nav` tree rewrite reflecting the new structure (every path in the current nav changes)
- `edit_uri` update for correct GitHub edit links

This configuration must be prototyped in a branch before the migration PR.

### External references (outside docs/)

Files outside `docs/` that reference `docs/` paths must be updated in the same PR:

- `AGENTS.md` — references `docs/architecture/protocols/actor-actor.md`, `docs/reference/abi-protocol.md`, etc.
- `deploy/README.md` — references `docs/install/local-kind.md`, `docs/install/aws-eks.md`
- `src/*/README.md` — component READMEs reference their architecture docs
- `examples/` READMEs — reference various docs paths
- `deploy/grafana-dashboards/README.md` — references `docs/architecture/observability.md`

**Implementation step**: `grep -r 'docs/' --include='*.md' . | grep -v docs/ | grep -v .aint/ | grep -v .venv/`
to find all external references and update them.

### High-complexity merges

These files require merging 3+ sources and need explicit section-by-section mapping:

| Target file | Sources | Complexity |
|-------------|---------|------------|
| `usage/guide-agentic-patterns.md` | `tutorials/agentic-patterns.md` + `explanation/agentic-design.md` + `reference/agentic-cheatsheet.md` | High — triple merge |
| `usage/guide-handler-patterns.md` | `tutorials/actor-handler-adapter-pattern.md` + `howto/add-new-actor.md` | Medium — two complementary sources |
| `usage/guide-pause-resume.md` | `tutorials/pause-resume.md` + `features/task-pause.md` (explanation parts) | Medium |
| `setup/ops-monitoring.md` | `operate/monitoring.md` + `architecture/observability.md` | Medium |
| `reference/components/core-sidecar.md` | Existing `architecture/asya-sidecar.md` + `features/resiliency.md` (policy tables) + `internal/resiliency.md` (internals) | High — triple merge into existing large doc |
| `reference/components/core-crew.md` | Existing `architecture/asya-crew.md` + `internal/crew-checkpointer.md` (key format/schema) | Medium |
| `reference/components/core-gateway.md` | Existing `architecture/asya-gateway.md` + `internal/gateway-security.md` (auth schemes) | Medium |

These should use explicit section-by-section mapping during implementation, not blind concatenation.

### Migration constraints

1. **Single PR** — the migration must be atomic to avoid a period with half-broken links
2. **Prototype docs/website/ first** — verify mkdocs build works with the new directory layout before moving files
3. **Patch mkdocs.yml nav** — every path in the current `nav:` tree changes; rewrite the full nav to match the new structure; this is part of the migration PR, not a follow-up
4. **Fix broken references** — `docs/explanation/agentic-design.md` references non-existent `docs/architecture/gateway-security-model.md`; fix during migration
5. **Internal-to-public editorial pass** — `internal/gateway-api-spec.md` and `internal/gateway-security.md` need light editing when promoted to `reference/` (remove "internal" framing, add audience-appropriate context)

### Navigation convention

**README as hub, not book-style links.** Each section's README provides the reading order
and groups files into "Getting Started → Guides → Operations." Readers return to the README
to pick their next topic.

Inter-doc links are **contextual only** — "for more on flavors, see [guide-actor-flavors.md]" —
not sequential "next/previous" navigation. This avoids the maintenance chain where inserting
or reordering one doc requires updating multiple files.

### AGENTS.md updates

Add to AGENTS.md:

```markdown
### Documentation Policy Additions

- `docs/plans/` is gitignored and must never be committed. Use aint for work tracking.
- `docs/` contains only documentation content (.md files). Website assets live in `docs/website/`.
- Mirrored guides in `usage/` and `setup/` must cross-link each other.
```

### What does NOT change

- `CONTRIBUTING.md` (repo root) — stays as-is
- `AGENTS.md` — updated with doc policy additions
- `.aint/` — unchanged
- `examples/` — unchanged
- Source code — unchanged
