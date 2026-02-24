# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.5.1] - 2026-02-24

## Major Changes

* feat(1c4w): Actor Flavors — wire function-asya-flavors into Crossplane compositions (#194) @atemate
* feat(1c46): flexible sink/sump phases, gateway status.phase parsing, retry integration tests (#193) @atemate
* feat(runtime): add GET /healthz + rewrite sidecar-runtime protocol docs (epic 1fbe) (#192) @atemate
* feat(route): migrate actor routing to prev/curr/next format (epic 1iah) (#191) @atemate
* feat(runtime): replace binary framing with HTTP over Unix socket (#189) @atemate
* feat(flow): add fan-out parsing for list comprehensions, list literals, and `asyncio.gather` (#190) @atemate
* feat: Add mutating webhook to derive asya.sh/actor label from spec.actor (#188) @atemate
* feat: Add async flow example fixtures (ADK-based) (#174) @atemate
* feat(flow): add try-except-finally support to Flow DSL compiler (#185) @atemate
* feat(crew): two-layer termination with x-sink, x-sump, and hooks (#182) @atemate
* feat(crossplane,injector): resiliency config in XRD and ASYA\_RESILIENCY\_\* env injection (#183) @atemate
* feat(crew): add x-dlq standalone Go worker for infrastructure DLQ (#184) @atemate
* feat(sidecar): implement retry logic with exponential backoff (#181) @atemate
* feat(flow): add max\_iterations guard for while-True loops (#176) @atemate
* feat(sidecar): parse ASYA\_RESILIENCY\_\* env vars for retry configuration (#171) @atemate
* feat: Add function-asya-flavors Composition Function (#177) @atemate
* feat: Add status top-level field to message schema (#178) @atemate
* feat(crossplane): add spec.flavors field to AsyncActor XRD (#175) @atemate
* fix(ci): Remove diff.path that overwrites octocov baseline (#179) @atemate
* fix(ci): Add asya-injector to release and fix chart publishing (#173) @atemate
* feat(transport): add SendWithDelay() and rename Nack() to Requeue() (#172) @atemate
* feat(runtime): add fully qualified error type and MRO to error responses (#168) @atemate
* fix(ci): Enable DEBUG logging for octocov baseline diagnosis (#170) @atemate

## Other Changes

* feat(1c4w): Actor Flavors — wire function-asya-flavors into Crossplane compositions (#194) @atemate
* feat(1c46): flexible sink/sump phases, gateway status.phase parsing, retry integration tests (#193) @atemate
* feat(runtime): add GET /healthz + rewrite sidecar-runtime protocol docs (epic 1fbe) (#192) @atemate
* feat(route): migrate actor routing to prev/curr/next format (epic 1iah) (#191) @atemate
* feat(runtime): replace binary framing with HTTP over Unix socket (#189) @atemate
* feat(flow): add fan-out parsing for list comprehensions, list literals, and `asyncio.gather` (#190) @atemate
* feat: Add mutating webhook to derive asya.sh/actor label from spec.actor (#188) @atemate
* chore: Remove StatefulSet actor workload support (#186) @atemate
* feat: Add async flow example fixtures (ADK-based) (#174) @atemate
* feat(flow): add try-except-finally support to Flow DSL compiler (#185) @atemate
* feat(crew): two-layer termination with x-sink, x-sump, and hooks (#182) @atemate
* feat(crossplane,injector): resiliency config in XRD and ASYA\_RESILIENCY\_\* env injection (#183) @atemate
* feat(crew): add x-dlq standalone Go worker for infrastructure DLQ (#184) @atemate
* feat(sidecar): implement retry logic with exponential backoff (#181) @atemate
* feat(flow): add max\_iterations guard for while-True loops (#176) @atemate
* feat(sidecar): parse ASYA\_RESILIENCY\_\* env vars for retry configuration (#171) @atemate
* feat: Add function-asya-flavors Composition Function (#177) @atemate
* feat: Add status top-level field to message schema (#178) @atemate
* feat(crossplane): add spec.flavors field to AsyncActor XRD (#175) @atemate
* fix(ci): Add asya-injector to release and fix chart publishing (#173) @atemate
* feat(transport): add SendWithDelay() and rename Nack() to Requeue() (#172) @atemate
* feat(runtime): add fully qualified error type and MRO to error responses (#168) @atemate
* fix(ci): Enable DEBUG logging for octocov baseline diagnosis (#170) @atemate

## Installation

### Helm Charts

Add the Helm repository:
```bash
helm repo add asya https://asya.sh/charts
helm repo update
```

Install the Crossplane compositions and gateway:
```bash
helm install asya-crossplane asya/asya-crossplane \
  --version 0.5.1 \
  --namespace asya-system \
  --create-namespace
helm install asya-gateway asya/asya-gateway \
  --version 0.5.1 \
  --namespace asya
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-crew:0.5.1`
- `ghcr.io/deliveryhero/asya-gateway:0.5.1`
- `ghcr.io/deliveryhero/asya-injector:0.5.1`
- `ghcr.io/deliveryhero/asya-sidecar:0.5.1`
- `ghcr.io/deliveryhero/asya-testing:0.5.1`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)




## [0.5.0] - 2026-02-11

## Major Changes

* feat: Add `asya-playground` umbrella Helm chart for quickstart (#122) @atemate
* feat!: yield-only fan-out with streaming wire protocol (#166) @atemate
* fix(ci): Add root prefix to octocov github:// datastore URL (#167) @atemate
* feat(crossplane): Add RabbitMQ Crossplane composition (#161) @atemate
* feat(runtime): add async handler support (#165) @atemate
* feat(flow): add while loop support to Flow DSL compiler (#163) @atemate
* fix(ci): Use github:// datastore for octocov coverage reports (#164) @atemate
* fix(crossplane): Add function-auto-ready to fix XR Ready=False (#156) @atemate
* feat(crossplane): Add required spec.actor field to AsyncActor XRD (#159) @atemate
* feat(crossplane): Add ACTOR printer column to AsyncActor XRD (#158) @atemate
* fix(e2e): Add warm-up to concurrent envelope test to prevent flaky timeout (#155) @atemate
* feat(e2e): Migrate E2E tests to Crossplane architecture (#149) @atemate
* fix(charts): Fix labels: `actor` to `asya.sh/actor` (#153) @atemate
* feat(injector): Support custom Python executable via ASYA\_PYTHONEXECUTABLE env var (#152) @atemate
* fix(crossplane): Remove workloadRef from XRD schema (#154) @atemate
* feat(crossplane): Add transport-agnostic status fields to XRD (#151) @atemate
* feat(crossplane): Add sidecar imagePullPolicy and env to XRD (#150) @atemate
* fix(crossplane): Remove actorName field, use asya.sh/actor label (#148) @atemate
* fix(crossplane): Add credential tests, DRC selector, and workloadReady nil guard (#147) @atemate
* feat(crossplane): Add runtime ConfigMap to crossplane Helm chart (#146) @atemate
* feat(crossplane): Add Deployment and ScaledObject status patching (#140) @atemate
* fix(crossplane): Fix chart bugs and add Crossplane quickstart (#141) @atemate
* feat(injector): Add asya-injector mutating webhook for sidecar injection (#142) @atemate
* feat(crossplane): Add status patching to SQS Composition (#139) @atemate
* feat(crossplane): Add KEDA TriggerAuthentication to SQS Composition (#138) @atemate
* feat(crossplane): Add Deployment and ScaledObject to SQS Composition (#137) @atemate
* feat(crossplane): Add Phase 3 IRSA, KEDA, and Deployment support (#136) @atemate
* fix(crossplane): Address PR #134 review comments (#135) @atemate
* feat(crossplane): Add asya-crossplane Helm chart for Phase 1 Foundation (#134) @atemate

## Other Changes

* feat: Add `asya-playground` umbrella Helm chart for quickstart (#122) @atemate
* feat!: yield-only fan-out with streaming wire protocol (#166) @atemate
* feat(crossplane): Add RabbitMQ Crossplane composition (#161) @atemate
* feat(runtime): add async handler support (#165) @atemate
* feat(flow): add while loop support to Flow DSL compiler (#163) @atemate
* fix(ci): Use github:// datastore for octocov coverage reports (#164) @atemate
* refactor: Remove asya-operator, replace with Crossplane + injector (#160) @atemate
* fix(crossplane): Add function-auto-ready to fix XR Ready=False (#156) @atemate
* feat(crossplane): Add required spec.actor field to AsyncActor XRD (#159) @atemate
* refactor: rename Envelope to Message/Task across codebase (#162) @atemate
* feat(crossplane): Add ACTOR printer column to AsyncActor XRD (#158) @atemate
* fix(e2e): Add warm-up to concurrent envelope test to prevent flaky timeout (#155) @atemate
* feat(e2e): Migrate E2E tests to Crossplane architecture (#149) @atemate
* fix(charts): Fix labels: `actor` to `asya.sh/actor` (#153) @atemate
* feat(injector): Support custom Python executable via ASYA\_PYTHONEXECUTABLE env var (#152) @atemate
* fix(crossplane): Remove workloadRef from XRD schema (#154) @atemate
* feat(crossplane): Add transport-agnostic status fields to XRD (#151) @atemate
* feat(crossplane): Add sidecar imagePullPolicy and env to XRD (#150) @atemate
* fix(crossplane): Remove actorName field, use asya.sh/actor label (#148) @atemate
* fix(crossplane): Add credential tests, DRC selector, and workloadReady nil guard (#147) @atemate
* feat(crossplane): Add runtime ConfigMap to crossplane Helm chart (#146) @atemate
* feat(crossplane): Add Deployment and ScaledObject status patching (#140) @atemate
* fix(crossplane): Fix chart bugs and add Crossplane quickstart (#141) @atemate
* build(deps): Bump golang.org/x/oauth2 from 0.12.0 to 0.27.0 in /src/asya-injector (#145) @[dependabot[bot]](https://github.com/apps/dependabot)
* build(deps): Bump golang.org/x/net from 0.19.0 to 0.38.0 in /src/asya-injector (#144) @[dependabot[bot]](https://github.com/apps/dependabot)
* build(deps): Bump google.golang.org/protobuf from 1.31.0 to 1.33.0 in /src/asya-injector (#143) @[dependabot[bot]](https://github.com/apps/dependabot)
* feat(injector): Add asya-injector mutating webhook for sidecar injection (#142) @atemate
* feat(crossplane): Add status patching to SQS Composition (#139) @atemate
* feat(crossplane): Add KEDA TriggerAuthentication to SQS Composition (#138) @atemate
* feat(crossplane): Add Deployment and ScaledObject to SQS Composition (#137) @atemate
* feat(crossplane): Add Phase 3 IRSA, KEDA, and Deployment support (#136) @atemate
* fix(crossplane): Address PR #134 review comments (#135) @atemate
* feat(crossplane): Add asya-crossplane Helm chart for Phase 1 Foundation (#134) @atemate
* test(sidecar): Add regression tests for json.RawMessage payload optimization (#133) @atemate

## Installation

### Helm Charts

Add the Helm repository:
```bash
helm repo add asya https://asya.sh/charts
helm repo update
```

Install the Crossplane compositions and gateway:
```bash
helm install asya-crossplane asya/asya-crossplane \
  --version 0.5.0 \
  --namespace asya-system \
  --create-namespace
helm install asya-gateway asya/asya-gateway \
  --version 0.5.0 \
  --namespace asya
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-gateway:0.5.0`
- `ghcr.io/deliveryhero/asya-sidecar:0.5.0`
- `ghcr.io/deliveryhero/asya-crew:0.5.0`
- `ghcr.io/deliveryhero/asya-testing:0.5.0`

## Contributors

@atemate, @dependabot[bot], @github-actions[bot], [dependabot[bot]](https://github.com/apps/dependabot) and [github-actions[bot]](https://github.com/apps/github-actions)




## [0.4.2] - 2026-02-03

## Major Changes

* fix(sidecar): Include error status in messagesProcessed metric (#130) @atemate
* fix(ci): Use dedicated octocov branch for coverage baseline (#129) @atemate
* feat: Add initial Grafana dashboard for Asya actors (#116) @atemate

## Other Changes

* fix(ci): Use dedicated octocov branch for coverage baseline (#129) @atemate
* feat: Add initial Grafana dashboard for Asya actors (#116) @atemate

## Installation

### CRDs

Install or upgrade AsyncActor CRDs:
```bash
kubectl apply -f https://github.com/deliveryhero/asya/releases/download/0.4.2/asya-crds.yaml
```

### Helm Charts

Add the Helm repository:
```bash
helm repo add asya https://asya.sh/charts
helm repo update
```

Install the operator:
```bash
helm install asya-operator asya/asya-operator \
  --version 0.4.2 \
  --namespace asya-system \
  --create-namespace
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.4.2`
- `ghcr.io/deliveryhero/asya-gateway:0.4.2`
- `ghcr.io/deliveryhero/asya-sidecar:0.4.2`
- `ghcr.io/deliveryhero/asya-crew:0.4.2`
- `ghcr.io/deliveryhero/asya-testing:0.4.2`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)



## [0.4.1] - 2026-02-03

## Major Changes

* fix(ci): Add explicit verification to Helm chart publishing (#127) @atemate
* fix(operator): Clear deployment replicas field when KEDA scaling enabled (#125) @atemate
* feat(claude): Add fix-pr-e2e skill for optimized PR E2E test fixing (#123) @atemate
* fix(e2e): use imagePullPolicy: Never for local-only images (#114) @atemate

## Other Changes

* fix(ci): Add explicit verification to Helm chart publishing (#127) @atemate
* refactor: Gateway Helm chart to operator's transport pattern (#119) @atemate
* fix(operator): Clear deployment replicas field when KEDA scaling enabled (#125) @atemate
* docs: Add note about never editing .beads/ files manually to AGENTS.md (#126) @atemate
* feat(claude): Add fix-pr-e2e skill for optimized PR E2E test fixing (#123) @atemate
* build(deps): Consolidate dependency bumps with E2E fixes (#118) @atemate
* docs: Fix gateway namespace in quickstart (`asya-system` → `default`) (#120) @atemate
* docs: Complete Gateway section in quickstart README (#117) @atemate
* build(deps): Bump github.com/expr-lang/expr from 1.17.0 to 1.17.7 in /testing/component/operator/runtime\_configmap (#91) @[dependabot[bot]](https://github.com/apps/dependabot)
* build(deps): Bump github.com/kedacore/keda/v2 from 2.14.0 to 2.17.3 in /testing/integration/operator (#89) @[dependabot[bot]](https://github.com/apps/dependabot)
* charts(crew): improve `asya-crew` Helm chart configurability (#113) @atemate
* charts(operator): Bind `asya-sidecar` version to operator version in Helm chart (#112) @atemate
* fix(e2e): use imagePullPolicy: Never for local-only images (#114) @atemate
* chore: initialize beads for task management (#111) @atemate
* docs: Cleanup docs, add asya flow commands, drop asya flow init (#110) @atemate

## Installation

### CRDs

Install or upgrade AsyncActor CRDs:
```bash
kubectl apply -f https://github.com/deliveryhero/asya/releases/download/0.4.1/asya-crds.yaml
```

### Helm Charts

Add the Helm repository:
```bash
helm repo add asya https://asya.sh/charts
helm repo update
```

Install the operator:
```bash
helm install asya-operator asya/asya-operator \
  --version 0.4.1 \
  --namespace asya-system \
  --create-namespace
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.4.1`
- `ghcr.io/deliveryhero/asya-gateway:0.4.1`
- `ghcr.io/deliveryhero/asya-sidecar:0.4.1`
- `ghcr.io/deliveryhero/asya-crew:0.4.1`
- `ghcr.io/deliveryhero/asya-testing:0.4.1`

## Contributors

@atemate, @dependabot[bot], @github-actions[bot], [dependabot[bot]](https://github.com/apps/dependabot) and [github-actions[bot]](https://github.com/apps/github-actions)




## [0.4.0] - 2026-01-26

## Major Changes

* feat(operator)!: Do not set "app" K8s label to resources (#108) @atemate
* feat(operator)!: Use K8s labels only instead of resource names (#104) @atemate

## Other Changes

* feat(operator)!: Do not set "app" K8s label to resources (#108) @atemate
* feat(operator)!: Use K8s labels only instead of resource names (#104) @atemate

## Installation

### CRDs

Install or upgrade AsyncActor CRDs:
```bash
kubectl apply -f https://github.com/deliveryhero/asya/releases/download/1.0.0/asya-crds.yaml
```

### Helm Charts

Add the Helm repository:
```bash
helm repo add asya https://asya.sh/charts
helm repo update
```

Install the operator:
```bash
helm install asya-operator asya/asya-operator \
  --version 1.0.0 \
  --namespace asya-system \
  --create-namespace
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:1.0.0`
- `ghcr.io/deliveryhero/asya-gateway:1.0.0`
- `ghcr.io/deliveryhero/asya-sidecar:1.0.0`
- `ghcr.io/deliveryhero/asya-crew:1.0.0`
- `ghcr.io/deliveryhero/asya-testing:1.0.0`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)




## [0.3.10] - 2026-01-26

## Major Changes

* fix(operator): Fix operator race condition, fix error for Napping state (#98) @atemate

## Other Changes

* docs: Update bucket name in docs - 2 (#106) @atemate
* docs: Update bucket name in docs (#105) @atemate
* fix(operator): Fix operator race condition, fix error for Napping state (#98) @atemate

## Installation

### CRDs

Install or upgrade AsyncActor CRDs:
```bash
kubectl apply -f https://github.com/deliveryhero/asya/releases/download/0.3.10/asya-crds.yaml
```

### Helm Charts

Add the Helm repository:
```bash
helm repo add asya https://asya.sh/charts
helm repo update
```

Install the operator:
```bash
helm install asya-operator asya/asya-operator \
  --version 0.3.10 \
  --namespace asya-system \
  --create-namespace
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.10`
- `ghcr.io/deliveryhero/asya-gateway:0.3.10`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.10`
- `ghcr.io/deliveryhero/asya-crew:0.3.10`
- `ghcr.io/deliveryhero/asya-testing:0.3.10`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)




## [0.3.9] - 2026-01-06

## Other Changes

* chore: Update Crew charts to hard-code ASYA\_ env vars (#96) @atemate
* docs: Update changelog for last releases (#94) @atemate

## Installation

### CRDs

Install or upgrade AsyncActor CRDs:
```bash
kubectl apply -f https://github.com/deliveryhero/asya/releases/download/0.3.9/asya-crds.yaml
```

### Helm Charts

Add the Helm repository:
```bash
helm repo add asya https://asya.sh/charts
helm repo update
```

Install the operator:
```bash
helm install asya-operator asya/asya-operator \
  --version 0.3.9 \
  --namespace asya-system \
  --create-namespace
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.9`
- `ghcr.io/deliveryhero/asya-gateway:0.3.9`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.9`
- `ghcr.io/deliveryhero/asya-crew:0.3.9`
- `ghcr.io/deliveryhero/asya-testing:0.3.9`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)




## [0.3.8] - 2025-12-31

## Other Changes

* ci: Upload CRD on each main commit (#90) @atemate

## Installation

### CRDs

Install or upgrade AsyncActor CRDs:
```bash
kubectl apply -f https://github.com/deliveryhero/asya/releases/download/0.3.8/asya-crds.yaml
```

### Helm Charts

Add the Helm repository:
```bash
helm repo add asya https://asya.sh/charts
helm repo update
```

Install the operator:
```bash
helm install asya-operator asya/asya-operator \
  --version 0.3.8 \
  --namespace asya-system \
  --create-namespace
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.8`
- `ghcr.io/deliveryhero/asya-gateway:0.3.8`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.8`
- `ghcr.io/deliveryhero/asya-crew:0.3.8`
- `ghcr.io/deliveryhero/asya-testing:0.3.8`

## Contributors

@atemate


## [0.3.7] - 2025-12-19

* No changes

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.7`
- `ghcr.io/deliveryhero/asya-gateway:0.3.7`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.7`
- `ghcr.io/deliveryhero/asya-crew:0.3.7`
- `ghcr.io/deliveryhero/asya-testing:0.3.7`

## Contributors

@atemate



## [0.3.6] - 2025-12-19


## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.6`
- `ghcr.io/deliveryhero/asya-gateway:0.3.6`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.6`
- `ghcr.io/deliveryhero/asya-crew:0.3.6`
- `ghcr.io/deliveryhero/asya-testing:0.3.6`

## Contributors

@atemate



## [0.3.5] - 2025-12-19

* No changes

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.5`
- `ghcr.io/deliveryhero/asya-gateway:0.3.5`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.5`
- `ghcr.io/deliveryhero/asya-crew:0.3.5`
- `ghcr.io/deliveryhero/asya-testing:0.3.5`

## Contributors

@atemate


## [0.3.4] - 2025-12-19

## Other Changes

* ci: Improve CRD upload with debugging and verification (#82) @atemate

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.4`
- `ghcr.io/deliveryhero/asya-gateway:0.3.4`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.4`
- `ghcr.io/deliveryhero/asya-crew:0.3.4`
- `ghcr.io/deliveryhero/asya-testing:0.3.4`

## Contributors

@atemate and @github-actions[bot]


## [0.3.3] - 2025-12-19

## Major Changes

* fix(charts): Disable RabbitMQ transport enabled by default (#69) @atemate

## Other Changes

* docs: Add quickstart plans (#80) @atemate
* docs: Set Quick Start button to go to All not DS (#79) @atemate
* docs: Small docs cleanup, replace Asya🎭 with 🎭 (#77) @atemate
* docs: Add onboarding readme, fix docs, fix formatting (#72) @atemate
* fix(charts): Disable RabbitMQ transport enabled by default (#69) @atemate

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.3`
- `ghcr.io/deliveryhero/asya-gateway:0.3.3`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.3`
- `ghcr.io/deliveryhero/asya-crew:0.3.3`
- `ghcr.io/deliveryhero/asya-testing:0.3.3`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)


## [0.3.2] - 2025-12-16

## Changes
- ci: Fix CRD upload on release (#70)


## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.2`
- `ghcr.io/deliveryhero/asya-gateway:0.3.2`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.2`
- `ghcr.io/deliveryhero/asya-crew:0.3.2`
- `ghcr.io/deliveryhero/asya-testing:0.3.2`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)


## [0.3.1] - 2025-12-16

## Major Changes

* fix(charts): Update images repository to ghcr.io (#65) @ghost

## Other Changes

* fix(charts): Update images repository to ghcr.io (#65) @ghost
* style: Simplify css by re-using stylesheets file (#66) @ghost
* ci: Add asya-crds yaml to release artifacts (#67) @ghost

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.1`
- `ghcr.io/deliveryhero/asya-gateway:0.3.1`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.1`
- `ghcr.io/deliveryhero/asya-crew:0.3.1`
- `ghcr.io/deliveryhero/asya-testing:0.3.1`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)


## [0.3.0] - 2025-12-15

## Major Changes

* feat: Add basic support for flows (#58) @atemate-dh
* refactor(asya-cli)!: Consolidate tools into single `asya` CLI with subcommands (#59) @atemate-dh

## Other Changes

* docs: Add landing page for asya.sh, deploy charts to asya.sh/charts (#62) @atemate-dh
* chore: Increase verbosity of helm tests (#61) @atemate-dh
* feat: Add basic support for flows (#58) @atemate-dh
* ci: Try to fix Octocov coverage again again (#60) @atemate-dh
* refactor(asya-cli)!: Consolidate tools into single `asya` CLI with subcommands (#59) @atemate-dh

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:1.0.0`
- `ghcr.io/deliveryhero/asya-gateway:1.0.0`
- `ghcr.io/deliveryhero/asya-sidecar:1.0.0`
- `ghcr.io/deliveryhero/asya-crew:1.0.0`
- `ghcr.io/deliveryhero/asya-testing:1.0.0`

## Contributors

@atemate-dh, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)


## [0.2.0] - 2025-12-04

## Major Changes

* feat: Implement namespace-aware queue naming (#46) @atemate-dh
* feat: Propagate labels from CR to owned resources (#45) @atemate-dh
* bug: Fix bug disallowing class handlers without a constructor (#43) @atemate-dh
* feat: Enable creation of asyas in different namespaces (#41) @atemate-dh
* fix: Put Queue deletion under `ASYA_DISABLE_QUEUE_MANAGEMENT` feature flag (#31) @atemate-dh

## Other Changes

* chore: Bump asya-gateway dep: golang.org/x/crypto 0.37.0 -> 0.45.0 (#56) @atemate-dh
* ci: Try to fix Octocov coverage again (#55) @atemate-dh
* feat: Implement namespace-aware queue naming (#46) @atemate-dh
* ci: Simplify release categories 7 (#54) @atemate-dh
* ci: Simplify release categories 6 (#53) @atemate-dh
* ci: Simplify release categories 5 (#52) @atemate-dh
* ci: Simplify release categories 4 (#51) @atemate-dh
* ci: Simplify release categories 3 (#50) @atemate-dh
* ci: Simplify release categories 2 (#49) @atemate-dh
* ci: Simplify release categories (#47) @atemate-dh
* ci: Fix octocov persistance for main branch again (#48) @atemate-dh
* feat: Propagate labels from CR to owned resources (#45) @atemate-dh
* fix: Add datastores to octocov summary section for baseline comparison (#44) @atemate-dh
* bug: Fix bug disallowing class handlers without a constructor (#43) @atemate-dh
* feat: Enable creation of asyas in different namespaces (#41) @atemate-dh
* ci: Improve PR labels (#42) @atemate-dh
* build: Adapt local setup for macOS (#36) @atemate-dh
* build: Fix CI Octocov coverage - main not saving results (#37) @atemate-dh
* build: Upgrade Go from 1.23 to 1.24 (#34) @atemate-dh
* Clarify e2e docs and dedupe platform quickstart (#29) @msaharan
* docs: Update E2E README to match current make targets (#24) @msaharan
* fix: Put Queue deletion under `ASYA_DISABLE_QUEUE_MANAGEMENT` feature flag (#31) @atemate-dh
* fix: Sidecar integration tests for macOS (#32) @atemate-dh
* fix: Enable coverage reporting for e2e tests and fix CI artifact paths (#33) @atemate-dh
* docs: Align Local Kind install guide with current e2e profiles and Helm workflow (#25) @msaharan
* chore: Fix root make test-e2e target to run actual e2e flow (#28) @msaharan
* docs: fix architecture link text in data scientists quickstart (#27) @msaharan
* fix: Delete unneeded ASYA\_SKIP\_QUEUE\_OPERATION env var (#30) @atemate-dh
* docs: Align RabbitMQ transport doc and shared compose README with current tooling (#26) @msaharan

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.2.0`
- `ghcr.io/deliveryhero/asya-gateway:0.2.0`
- `ghcr.io/deliveryhero/asya-sidecar:0.2.0`
- `ghcr.io/deliveryhero/asya-crew:0.2.0`
- `ghcr.io/deliveryhero/asya-testing:0.2.0`

## Contributors

@atemate-dh, @github-actions[bot], @msaharan and [github-actions[bot]](https://github.com/apps/github-actions)


## [0.1.1] - 2025-11-18

## What's Changed

## Documentation

- Fix Documentation rendering, fix search @atemate-dh (#18)
- Minor: Polish documentation @atemate-dh (#16)
- feat: Update all documentation, add GitHub Pages @atemate-dh (#15)
- feat: Add queue health monitoring with automatic queue recreation @atemate-dh (#9)
- Update CHANGELOG.md for v0.1.0 @[github-actions[bot]](https://github.com/apps/github-actions) (#7)

## Testing

- fix: Update test configuration to match envelope store refactoring @atemate-dh (#17)
- feat: Update all documentation, add GitHub Pages @atemate-dh (#15)
- bug: Fix KEDA/HPA race condition @atemate-dh (#14)
- feat: Add queue health monitoring with automatic queue recreation @atemate-dh (#9)

## Infrastructure

- Fix Documentation rendering, fix search @atemate-dh (#18)
- fix: Update test configuration to match envelope store refactoring @atemate-dh (#17)
- Minor: Polish documentation @atemate-dh (#16)
- feat: Update all documentation, add GitHub Pages @atemate-dh (#15)
- feat: Add queue health monitoring with automatic queue recreation @atemate-dh (#9)

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.1.1`
- `ghcr.io/deliveryhero/asya-gateway:0.1.1`
- `ghcr.io/deliveryhero/asya-sidecar:0.1.1`
- `ghcr.io/deliveryhero/asya-crew:0.1.1`
- `ghcr.io/deliveryhero/asya-testing:0.1.1`

## Contributors

@atemate-dh, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)


## [0.1.0] - 2025-11-17

## What's Changed

- Scaffold release CI with ghcr.io, adjust Operator resources @atemate-dh (#4)
- Improve main README.md, fix e2e tests @atemate-dh (#3)
- Add asya @atemate-dh (#2)
- Revert to initial commit state @atemate-dh (#1)

## Testing

- feat: Add error details extraction in error-end actor @atemate-dh (#6)
- fix: Sidecar should not access transport to verify queue readiness @atemate-dh (#5)

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.1.0`
- `ghcr.io/deliveryhero/asya-gateway:0.1.0`
- `ghcr.io/deliveryhero/asya-sidecar:0.1.0`
- `ghcr.io/deliveryhero/asya-crew:0.1.0`
- `ghcr.io/deliveryhero/asya-testing:0.1.0`

## Contributors

@atemate-dh and @nmertaydin

### Added
- CI workflow for publishing Docker images on GitHub releases
- Automated changelog generation using release-drafter
- Release workflow for building and publishing asya-* images to ghcr.io

[0.1.0]: https://github.com/deliveryhero/asya/releases/tag/v0.1.0

[0.1.1]: https://github.com/deliveryhero/asya/releases/tag/v0.1.1


[0.2.0]: https://github.com/deliveryhero/asya/releases/tag/v0.2.0


[0.3.0]: https://github.com/deliveryhero/asya/releases/tag/v0.3.0


[0.3.1]: https://github.com/deliveryhero/asya/releases/tag/v0.3.1


[0.3.2]: https://github.com/deliveryhero/asya/releases/tag/v0.3.2


[0.3.3]: https://github.com/deliveryhero/asya/releases/tag/v0.3.3


[0.3.4]: https://github.com/deliveryhero/asya/releases/tag/v0.3.4


[0.3.9]: https://github.com/deliveryhero/asya/releases/tag/v0.3.9


[0.3.10]: https://github.com/deliveryhero/asya/releases/tag/v0.3.10


[0.4.0]: https://github.com/deliveryhero/asya/releases/tag/v0.4.0


[0.4.1]: https://github.com/deliveryhero/asya/releases/tag/v0.4.1


[0.4.2]: https://github.com/deliveryhero/asya/releases/tag/v0.4.2


[0.5.0]: https://github.com/deliveryhero/asya/releases/tag/v0.5.0


[Unreleased]: https://github.com/deliveryhero/asya/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/deliveryhero/asya/releases/tag/v0.5.1

