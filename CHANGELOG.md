# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [1.1.2] - 2026-04-24

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Features
* feat(state-proxy): DuckDB /query for S3/GCS Python connectors [i0ewl] by @atemate in https://github.com/deliveryhero/asya/pull/463
* feat(state-proxy): pvc-kv connector — inmem + PVC + DuckDB /query [m4d5u] by @atemate in https://github.com/deliveryhero/asya/pull/464
* feat(e2e): enable observability stack in all profiles and fix dead env vars [lbilw] by @atemate in https://github.com/deliveryhero/asya/pull/466
* feat(loadtest): add asya-loadtest standalone Helm chart with k6 by @atemate in https://github.com/deliveryhero/asya/pull/467


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v1.1.1...v1.1.2



## [1.1.0] - 2026-04-21

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Features
* feat(gateway): PR1 — PG state-proxy connector + asya-mesh-api core by @atemate in https://github.com/deliveryhero/asya/pull/442
* feat(gateway): PR2 — MCP Streamable HTTP + A2A JSON-RPC adapters by @atemate in https://github.com/deliveryhero/asya/pull/444
* feat(sidecar): PR3 — envelope gateway URL + unified events + pre-flight check by @atemate in https://github.com/deliveryhero/asya/pull/443
* feat(gateway): PR4 — Helm chart + Ingress + Crossplane integration by @atemate in https://github.com/deliveryhero/asya/pull/445
* feat(crossplane): add initContainers and sidecars to AsyncActor XRD [cynl0] by @atemate in https://github.com/deliveryhero/asya/pull/452
### Bug Fixes
* fix(asya-lab): decouple PyPI version from repo tags by @atemate in https://github.com/deliveryhero/asya/pull/446
* fix(lint): Fix lint by @atemate in https://github.com/deliveryhero/asya/pull/451
### Documentation
* chore: add DCO enforcement and CNCF sandbox prep by @atemate in https://github.com/deliveryhero/asya/pull/438
* docs: add frontmatter descriptions for agent discovery, fix mkdocs nav by @atemate in https://github.com/deliveryhero/asya/pull/441
* chore: Add GEMINI.md and CLAUDE.md by @atemate in https://github.com/deliveryhero/asya/pull/447


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v1.0.9...v1.1.0




## [1.0.9] - 2026-04-15

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Features
* feat(charts): configurable AWS resource tags for SQS queues by @atemate in https://github.com/deliveryhero/asya/pull/436

**Full Changelog**: https://github.com/deliveryhero/asya/compare/v1.0.7...v1.0.9



## [1.0.8] - 2026-04-15

<!-- Release notes generated using configuration in .github/release.yml at main -->

Same as v1.0.7 but includes commit https://github.com/deliveryhero/asya/commit/0eeb89aaff181dd9a75d2f8b0ccdeed32af4a36b

**Full Changelog**: https://github.com/deliveryhero/asya/compare/v1.0.6...v1.0.8



## [1.0.7] - 2026-04-15

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Bug Fixes
* fix(sidecar): RabbitMQ queue auto-creation and channel recovery by @atemate in https://github.com/deliveryhero/asya/pull/431
### Documentation
* docs(setup): EKS install guide — RBAC, missing values, troubleshooting by @atemate in https://github.com/deliveryhero/asya/pull/430
### Other Changes
* chore(deps): consolidate dependency updates and add dependabot grouping by @atemate in https://github.com/deliveryhero/asya/pull/419


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v1.0.6...v1.0.7




## [1.0.6] - 2026-04-14

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Bug Fixes
* fix(ci): remove fetch-tags from checkout — conflicts with release tags by @atemate in https://github.com/deliveryhero/asya/pull/423


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v1.0.4...v1.0.6



## [1.0.3], [1.0.4], [1.0.5] - 2026-04-14 (broken release workflows)

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Bug Fixes
* fix(ci): use git fetch --tags instead of fetch-tags checkout option by @atemate in https://github.com/deliveryhero/asya/pull/420
* fix(ci): only require major version confirmation on actual major bumps by @atemate in https://github.com/deliveryhero/asya/pull/417


## [1.0.2] - 2026-04-13

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Bug Fixes
* fix(charts): fail with clear message when ProviderConfig CRDs are missing by @atemate in https://github.com/deliveryhero/asya/pull/415
### Documentation
* docs: Restructure examples/ into curated teaser by @atemate in https://github.com/deliveryhero/asya/pull/413


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v1.0.1...v1.0.2



## [1.0.1] - 2026-03-25

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Features
* feat(asya-lab): CLI improvements — send/logs/trace, compiler fixes, kustomize patches by @atemate in https://github.com/deliveryhero/asya/pull/393


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.16...v1.0.1



## [0.5.16] - 2026-03-24

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Bug Fixes
* fix(crossplane): shorten default kubectl get asya view by @atemate in https://github.com/deliveryhero/asya/pull/399


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.15...v0.5.16



## [0.5.15] - 2026-03-24

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Bug Fixes
* fix(ci): fix asya-playground helm dependency build in release workflow by @atemate in https://github.com/deliveryhero/asya/pull/397
### Other Changes
* ci: simplify release workflow trigger by @atemate in https://github.com/deliveryhero/asya/pull/396


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.14...v0.5.15



## [0.5.14] - 2026-03-24

<!-- Release notes generated using configuration in .github/release.yml at main -->

## What's Changed
### Features
* feat: distributed tracing — OTEL instrumentation + Tempo in Grafana [kvx0] by @atemate in https://github.com/deliveryhero/asya/pull/391
* feat(gateway): surface result payload as A2A artifact [ar84] by @atemate in https://github.com/deliveryhero/asya/pull/392
* feat(grafana): add flow overview panels to Asya dashboard by @atemate in https://github.com/deliveryhero/asya/pull/394
### Other Changes
* ci: replace release-drafter with GitHub native release.yml by @atemate in https://github.com/deliveryhero/asya/pull/390


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.13...v0.5.14



## [0.5.13] - 2026-03-23

## Major Changes

* fix(crew): handle DeadlineExceeded as empty queue in scaler-pubsub [ws0s] (#388) @atemate

## Other Changes

* fix(crew): handle DeadlineExceeded as empty queue in scaler-pubsub [ws0s] (#388) @atemate

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
  --version 0.5.13 \
  --namespace asya-system \
  --create-namespace
helm install asya-gateway asya/asya-gateway \
  --version 0.5.13 \
  --namespace asya
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-crew:0.5.13`
- `ghcr.io/deliveryhero/asya-gateway:0.5.13`
- `ghcr.io/deliveryhero/asya-sidecar:0.5.13`
- `ghcr.io/deliveryhero/asya-testing:0.5.13`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)




## [0.5.12] - 2026-03-23

## What's Changed
* Update CHANGELOG.md for v0.5.11 by @github-actions[bot] in https://github.com/deliveryhero/asya/pull/382
* fix(website): favicon, pronunciation alignment, footer text by @atemate in https://github.com/deliveryhero/asya/pull/385
* feat(gateway-chart): projected volume for per-flow ConfigMaps [0mtj] by @atemate in https://github.com/deliveryhero/asya/pull/386
* feat(crew): KEDA external scaler for GCP Pub/Sub [wpla] by @atemate in https://github.com/deliveryhero/asya/pull/383


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.11...v0.5.12



## [0.5.11] - 2026-03-23

## What's Changed
* Update CHANGELOG.md for v0.5.10 by @github-actions[bot] in https://github.com/deliveryhero/asya/pull/370
* feat(compiler): adapter generation for @tool-decorated functions [syop] by @atemate in https://github.com/deliveryhero/asya/pull/365
* fix(compiler): adapter codegen — denormalize p→payload and add import [syop] by @atemate in https://github.com/deliveryhero/asya/pull/371
* feat(gateway): ephemeral FLY streaming via PG LISTEN/NOTIFY [jhre] by @atemate in https://github.com/deliveryhero/asya/pull/368


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.10...v0.5.11



## [0.5.10] - 2026-03-23

## What's Changed
* docs: add governance files and update copyright by @atemate in https://github.com/deliveryhero/asya/pull/358
* Update CHANGELOG.md for v0.5.9 by @github-actions[bot] in https://github.com/deliveryhero/asya/pull/359
* docs: use sun/moon icons for theme toggle on landing page by @atemate in https://github.com/deliveryhero/asya/pull/360
* fix(docs): align header logo with sidebar nav on desktop by @atemate in https://github.com/deliveryhero/asya/pull/361
* feat(compiler): unify rules — config-driven, no wildcards [hppv] by @atemate in https://github.com/deliveryhero/asya/pull/356
* feat(compiler): fix def-line directives, tenacity where-tree extraction, resiliency examples [o05n] by @atemate in https://github.com/deliveryhero/asya/pull/362
* fix: Semantic router naming: AST-based instead of line-number-based [tos9] by @atemate in https://github.com/deliveryhero/asya/pull/366
* fix(website): mobile responsive layout for landing page and docs by @atemate in https://github.com/deliveryhero/asya/pull/367
* docs(compiler): add compiler rules reference spec and usage guide [7wcf] by @atemate in https://github.com/deliveryhero/asya/pull/363
* fix(testing): pin LocalStack 4.4.0, fix JWKS startup & stale expose test by @atemate in https://github.com/deliveryhero/asya/pull/369
* fix(crossplane): enable watch on ScaledObject for status pipeline updates [mqd9] by @atemate in https://github.com/deliveryhero/asya/pull/364


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.9...v0.5.10



## [0.5.9] - 2026-03-22

## What's Changed
* Update CHANGELOG.md for v0.5.8 by @github-actions[bot] in https://github.com/deliveryhero/asya/pull/353
* feat(compiler): render context manager scopes as dashed subgraphs by @atemate in https://github.com/deliveryhero/asya/pull/355
* chore(deps): bump google.golang.org/grpc from 1.74.2 to 1.79.3 in /src/asya-sidecar by @dependabot[bot] in https://github.com/deliveryhero/asya/pull/354
* docs: improve website look, navigation, and content by @atemate in https://github.com/deliveryhero/asya/pull/357


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.8...v0.5.9



## [0.5.8] - 2026-03-22

## What's Changed
* Update CHANGELOG.md for v0.5.7 by @github-actions[bot] in https://github.com/deliveryhero/asya/pull/349
* feat(compiler): try/except support via sidecar retryRules [3dp2] by @atemate in https://github.com/deliveryhero/asya/pull/346
* docs: streamline README, fix website code blocks by @atemate in https://github.com/deliveryhero/asya/pull/345
* fix(docs): add missing guide-actor-xrd.md, fix pluggable-transport URL by @atemate in https://github.com/deliveryhero/asya/pull/351
* feat(compiler): rename manifest prefix asyncactor to asya, add actor- prefix [b5mg] by @atemate in https://github.com/deliveryhero/asya/pull/350
* fix(ci): preserve Helm charts when deploying docs to gh-pages by @atemate in https://github.com/deliveryhero/asya/pull/352


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.7...v0.5.8



## [0.5.7] - 2026-03-21

## What's Changed
* Update CHANGELOG.md for v0.5.5 by @github-actions[bot] in https://github.com/deliveryhero/asya/pull/318
* docs(gcp-gke): complete GKE + GCP Pub/Sub install guide for KubeCon demo by @atemate in https://github.com/deliveryhero/asya/pull/319
* fix(e2e): fix three bugs introduced by @flow decorator commit (#315) by @atemate in https://github.com/deliveryhero/asya/pull/322
* fix(state-proxy): implement exclusive create (xb mode) in server and CAS connectors by @atemate in https://github.com/deliveryhero/asya/pull/326
* feat(xrd): remove transport from AsyncActor spec, use defaultCompositionRef by @atemate in https://github.com/deliveryhero/asya/pull/321
* refactor(runtime): cleanup asya_runtime.py by @atemate in https://github.com/deliveryhero/asya/pull/324
* feat(dlq-worker): add GCS storage + Pub/Sub consumer for native GKE [y6xv] by @atemate in https://github.com/deliveryhero/asya/pull/323
* refactor(gateway): unify terminology — task=A2A, tool=MCP, envelope=mesh by @atemate in https://github.com/deliveryhero/asya/pull/325
* fix(charts): all transports and IRSA disabled by default by @atemate in https://github.com/deliveryhero/asya/pull/320
* refactor(cli): remove asya flow * subcommand, promote validate to top-level by @atemate in https://github.com/deliveryhero/asya/pull/314
* chore(deps): bump google.golang.org/grpc from 1.74.2 to 1.79.3 in /src/asya-gateway by @dependabot[bot] in https://github.com/deliveryhero/asya/pull/327
* chore(deps): bump google.golang.org/grpc from 1.79.2 to 1.79.3 in /src/asya-crew/cmd/dlq-worker by @dependabot[bot] in https://github.com/deliveryhero/asya/pull/328
* feat(compiler): union of PRs #278, #280, #307 — directives, decorators, rules engine by @atemate in https://github.com/deliveryhero/asya/pull/329
* docs: remove stale transport: field from AsyncActor spec examples by @atemate in https://github.com/deliveryhero/asya/pull/331
* feat(sidecar): x-asya-first-attempt header for maxDuration tracking by @atemate in https://github.com/deliveryhero/asya/pull/332
* chore: remove asya-actor helm chart by @atemate in https://github.com/deliveryhero/asya/pull/333
* fix(crew): x-sump must always be reached via x-sink (enforce two-layer termination) [nqf5] by @atemate in https://github.com/deliveryhero/asya/pull/330
* feat(sidecar): policy-based error handling — policies+rules replaces retry+nonRetryableErrors by @atemate in https://github.com/deliveryhero/asya/pull/334
* fix: Remove /mesh/expose — ConfigMap+hot-reload is the only tool registration mechanism [38we] by @atemate in https://github.com/deliveryhero/asya/pull/335
* chore(deps): bump github.com/buger/jsonparser from 1.1.1 to 1.1.2 in /src/asya-gateway by @dependabot[bot] in https://github.com/deliveryhero/asya/pull/336
* refactor(compiler): Phase 1 — replace ir/grouper/dotgen with analyzer/graphgen by @atemate in https://github.com/deliveryhero/asya/pull/337
* feat(compiler): Phase 2 — 5-step pipeline with manifest generation and FlowInfo by @atemate in https://github.com/deliveryhero/asya/pull/339
* feat(compiler): Phase 3 — flow composition, examples, validation by @atemate in https://github.com/deliveryhero/asya/pull/340
* docs: restructure documentation against Diataxis framework [u1zh] by @atemate in https://github.com/deliveryhero/asya/pull/338
* feat(compiler): per-scope semantics for context manager configs [ia37] by @atemate in https://github.com/deliveryhero/asya/pull/342
* docs: prettify repo for KubeCon by @atemate in https://github.com/deliveryhero/asya/pull/343
* fix(sidecar): log runtime error content at ERROR level by @atemate in https://github.com/deliveryhero/asya/pull/344
* chore(deps): bump google.golang.org/grpc from 1.74.2 to 1.79.3 in /testing/integration/sidecar by @dependabot[bot] in https://github.com/deliveryhero/asya/pull/341


**Full Changelog**: https://github.com/deliveryhero/asya/compare/v0.5.5...v0.5.7



## [0.5.4] - 2026-03-17

## Major Changes

* feat(compiler): require @flow decorator on flow entry points (#315) @atemate
* feat(branding): add project logos to README and website (#313) @atemate
* fix: Patch asya CLI configuration [pwsf] (#311) @atemate
* feat(flow): with/async with context manager support in flow compiler [2t1q] (#281) @atemate
* fix(compiler): include agentic flows in pre-commit + starred list comprehension gather [36g4] (#310) @atemate
* fix(compiler): if-at-end-of-while-body loses loop back-edge continuation (#309) @atemate
* feat(flavors): type-aware merge with conflict detection [ai6o] (#306) @atemate
* feat(cli): asya build + asya k commands [4g10] (#298) @atemate
* fix(compiler): handle list(await asyncio.gather(...)) as fan-out pattern (#304) @atemate
* feat(xrd)!: flatten AsyncActor workload spec — promote image/handler to root fields [lfcf] (#303) @atemate
* fix(flow-compiler): generate SVG instead of PNG for deterministic pre-commit flow diagrams [bvs4] (#302) @atemate
* feat(xrd): harmonize AsyncActor scaling spec with KEDA — rename min/maxReplicas, add additionalTriggers [8nhy] (#301) @atemate
* feat(sidecar): Unix socket transport for local Docker Compose testing [cavw] (#299) @atemate
* feat(crossplane)!: inline sidecar injection — render full pod spec in Crossplane compositions [af25] (#293) @atemate
* feat(cli): add compile, expose, show, status commands [5ifn] (#297) @atemate
* feat(compiler): manifest stamping with kustomize output [hox4] (#296) @atemate
* feat(cli): config system + asya init [pyt1] (#295) @atemate
* feat(xrd): remove provider-specific fields from AsyncActor XRD [8gc6] (#292) @atemate
* fix(e2e): increase pubsub-gcs status condition test timeout (#291) @atemate
* feat(runtime): smart JSON serialization for pydantic, dataclasses, typed structs [1mx1] (#279) @atemate
* feat(sidecar): stealth mode via x-asya-mesh-status: off header [4v09] (#284) @atemate
* fix(examples): validate and fix all AsyncActor examples for SQS transport (#286) @atemate
* feat(gateway): configurable ConfigMap poll interval (default 10s) (#283) @atemate
* feat(crossplane): add scaling.advanced to AsyncActor XRD [1ffa] (#276) @atemate
* feat(injector): K8s Secrets injection for AsyncActor [wcnw] (#282) @atemate
* feat(gateway): ConfigMap-based flow registry [zaai] (#277) @atemate
* feat(gateway): MCP API key + OAuth 2.1 auth [b51i+rcvm] (#271) @atemate
* feat(e2e): Crossplane DLQ support + drift detection tests + cold-start scaling (#270) @atemate
* fix(e2e): fix two root causes of failing e2e tests (#274) @atemate
* feat(gateway): GetTask history and artifacts from state proxy [tgfp] (#273) @atemate
* feat(gateway): Phase 1 — dual-deployment gateway split (api/mesh modes) [1fuy] (#269) @atemate
* feat(e2e): A2A protocol compliance e2e + integration tests (aint 0s9s) (#266) @atemate
* feat(cli): skip start router for single-actor flows [zmuh] (#267) @atemate
* feat(crew): simplify checkpointer key to {prefix}/{id}.json [nqv1] (#265) @atemate
* feat(gateway): A2A Phase 3 — JWT auth + Extended Agent Card [5vps] (#262) @atemate
* feat(gateway): DB-backed tool registry replacing YAML config [j1oh] (#261) @atemate
* fix(test): increase SLA integration test timeouts for CI reliability (#263) @atemate
* feat(gateway): Phase 1 Track B - A2A data layer refinements [tqel] (#260) @atemate
* fix: Un-xfail fan-out/fan-in E2E tests: VFS→ABI migration + stateProxy overlay (#255) @atemate
* feat(gateway): A2A Phase 2 — ListTasks, CancelTask, blocking, auth, FLY helpers (#259) @atemate
* feat(gateway): A2A Phase 1 — replace hand-rolled types with a2a-go v0.3.7 (#257) @atemate
* feat: add Pub/Sub + GCS test profiles (integration + E2E) (#256) @atemate
* feat(crossplane): propagate user labels from AsyncActor to composed resources (#253) @atemate
* feat(state-proxy): add GCS bucket connectors (CAS + LWW) (#250) @atemate
* feat(transport): add Google Cloud Pub/Sub transport support (#251) @atemate
* feat(sidecar): stream SSE frames instead of buffering (#242) @atemate
* fix(e2e): reduce CPU requests to fit 4-CPU CI Kind node (#254) @atemate
* feat(state-proxy): xattr-based metadata API for backend attributes (#249) @atemate
* fix(flow): improve fan-out detection and fix break routing in while loops (#246) @atemate
* feat(e2e): local OCI registry for function-asya-overlays (#244) @atemate
* feat(flow): expand compiler syntax support and improve error messages (#243) @atemate
* fix(sidecar): close TOCTOU race between SLA pre-check and effectiveTimeout (#236) @atemate
* feat!: replace VFS with yield-based ABI protocol for actor-runtime communication (#239) @atemate
* feat(crew): built-in persistence flavors for checkpointer (debt/1k5a8e) (#224) @atemate
* fix(release): use local URLs in helm index for playground dep build (#232) @atemate

## Other Changes

* feat(compiler): require @flow decorator on flow entry points (#315) @atemate
* feat(branding): add project logos to README and website (#313) @atemate
* docs: agentic patterns tutorial + ABI actor examples (streaming, dynamic routing, pause/resume) [amn1] (#285) @atemate
* fix: Patch asya CLI configuration [pwsf] (#311) @atemate
* docs(quickstart): simplify happy path, fix playground chart bugs (#312) @atemate
* feat(flow): with/async with context manager support in flow compiler [2t1q] (#281) @atemate
* fix(compiler): include agentic flows in pre-commit + starred list comprehension gather [36g4] (#310) @atemate
* fix(compiler): if-at-end-of-while-body loses loop back-edge continuation (#309) @atemate
* feat(flavors): type-aware merge with conflict detection [ai6o] (#306) @atemate
* feat(cli): asya build + asya k commands [4g10] (#298) @atemate
* fix(compiler): handle list(await asyncio.gather(...)) as fan-out pattern (#304) @atemate
* feat(xrd)!: flatten AsyncActor workload spec — promote image/handler to root fields [lfcf] (#303) @atemate
* fix(flow-compiler): generate SVG instead of PNG for deterministic pre-commit flow diagrams [bvs4] (#302) @atemate
* feat(xrd): harmonize AsyncActor scaling spec with KEDA — rename min/maxReplicas, add additionalTriggers [8nhy] (#301) @atemate
* feat(sidecar): Unix socket transport for local Docker Compose testing [cavw] (#299) @atemate
* feat(crossplane)!: inline sidecar injection — render full pod spec in Crossplane compositions [af25] (#293) @atemate
* feat(cli): add compile, expose, show, status commands [5ifn] (#297) @atemate
* feat(compiler): manifest stamping with kustomize output [hox4] (#296) @atemate
* feat(cli): config system + asya init [pyt1] (#295) @atemate
* chore: Actualize and optimize AGENTS.md (#294) @atemate
* feat(xrd): remove provider-specific fields from AsyncActor XRD [8gc6] (#292) @atemate
* refactor(flavors): simplify merge, write resolved spec back to XR [u5pd] (#290) @atemate
* fix(e2e): increase pubsub-gcs status condition test timeout (#291) @atemate
* chore: Revert: rename overlay back to flavor (#233) (#288) @atemate
* feat(runtime): smart JSON serialization for pydantic, dataclasses, typed structs [1mx1] (#279) @atemate
* feat(sidecar): stealth mode via x-asya-mesh-status: off header [4v09] (#284) @atemate
* fix(examples): validate and fix all AsyncActor examples for SQS transport (#286) @atemate
* feat(gateway): configurable ConfigMap poll interval (default 10s) (#283) @atemate
* feat(crossplane): add scaling.advanced to AsyncActor XRD [1ffa] (#276) @atemate
* feat(injector): K8s Secrets injection for AsyncActor [wcnw] (#282) @atemate
* feat(gateway): ConfigMap-based flow registry [zaai] (#277) @atemate
* docs(internal): gateway security model reference [4iga] (#275) @atemate
* test(e2e): SLA and gateway backstop race tests [1kow] (#272) @atemate
* feat(gateway): MCP API key + OAuth 2.1 auth [b51i+rcvm] (#271) @atemate
* feat(e2e): Crossplane DLQ support + drift detection tests + cold-start scaling (#270) @atemate
* fix(e2e): fix two root causes of failing e2e tests (#274) @atemate
* feat(gateway): GetTask history and artifacts from state proxy [tgfp] (#273) @atemate
* docs(tutorials): add adapter-pattern tutorial [p5nr] (#268) @atemate
* feat(gateway): Phase 1 — dual-deployment gateway split (api/mesh modes) [1fuy] (#269) @atemate
* feat(e2e): A2A protocol compliance e2e + integration tests (aint 0s9s) (#266) @atemate
* feat(cli): skip start router for single-actor flows [zmuh] (#267) @atemate
* feat(crew): simplify checkpointer key to {prefix}/{id}.json [nqv1] (#265) @atemate
* feat(gateway): A2A Phase 3 — JWT auth + Extended Agent Card [5vps] (#262) @atemate
* feat(gateway): DB-backed tool registry replacing YAML config [j1oh] (#261) @atemate
* docs(internal): extend transport and state-proxy testing docs to all test levels (#264) @atemate
* ci(e2e): enable Pub/Sub + GCS profile in E2E test matrix (#258) @atemate
* fix(test): increase SLA integration test timeouts for CI reliability (#263) @atemate
* feat(gateway): Phase 1 Track B - A2A data layer refinements [tqel] (#260) @atemate
* fix: Un-xfail fan-out/fan-in E2E tests: VFS→ABI migration + stateProxy overlay (#255) @atemate
* feat(gateway): A2A Phase 2 — ListTasks, CancelTask, blocking, auth, FLY helpers (#259) @atemate
* feat(gateway): A2A Phase 1 — replace hand-rolled types with a2a-go v0.3.7 (#257) @atemate
* feat: add Pub/Sub + GCS test profiles (integration + E2E) (#256) @atemate
* refactor: rename Message to back Envelope and /tasks/ to /mesh/ (#245) @atemate
* feat(crossplane): propagate user labels from AsyncActor to composed resources (#253) @atemate
* docs: add 15 agentic flow patterns with compiled output (#252) @atemate
* feat(state-proxy): add GCS bucket connectors (CAS + LWW) (#250) @atemate
* feat(transport): add Google Cloud Pub/Sub transport support (#251) @atemate
* feat(sidecar): stream SSE frames instead of buffering (#242) @atemate
* fix(e2e): reduce CPU requests to fit 4-CPU CI Kind node (#254) @atemate
* perf(e2e): cut E2E runtime from 80min to 31min with SQS tuning and NodePort (#248) @atemate
* feat(state-proxy): xattr-based metadata API for backend attributes (#249) @atemate
* fix(flow): improve fan-out detection and fix break routing in while loops (#246) @atemate
* feat(e2e): local OCI registry for function-asya-overlays (#244) @atemate
* feat(flow): expand compiler syntax support and improve error messages (#243) @atemate
* fix(sidecar): close TOCTOU race between SLA pre-check and effectiveTimeout (#236) @atemate
* test(e2e): clean up scaling tests, upgrade Kind to k8s 1.32, reduce S3 log noise (#234) @atemate
* docs: replace VFS references with ABI yield protocol (#241) @atemate
* docs: add ABI protocol reference with testing patterns (#240) @atemate
* docs: add Flow DSL reference with CPS explanation (#238) @atemate
* feat!: replace VFS with yield-based ABI protocol for actor-runtime communication (#239) @atemate
* refactor: rename flavor to overlay across the codebase (#233) @atemate
* feat(crew): built-in persistence flavors for checkpointer (debt/1k5a8e) (#224) @atemate
* test(flow): ADK LLM Auditor compilation and execution tests (#219) @atemate
* docs: update CHANGELOG.md for v0.5.1 and v0.5.4 (#231) @[github-actions[bot]](https://github.com/apps/github-actions)
* fix(release): use local URLs in helm index for playground dep build (#232) @atemate

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
  --version 0.5.4 \
  --namespace asya-system \
  --create-namespace
helm install asya-gateway asya/asya-gateway \
  --version 0.5.4 \
  --namespace asya
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-crew:0.5.4`
- `ghcr.io/deliveryhero/asya-gateway:0.5.4`
- `ghcr.io/deliveryhero/asya-sidecar:0.5.4`
- `ghcr.io/deliveryhero/asya-testing:0.5.4`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)




## [0.5.3] - 2026-02-27

## Major Changes

* feat(crew): built-in persistence flavors for checkpointer (debt/1k5a8e) (#224) @atemate
* fix(release): use local URLs in helm index for playground dep build (#232) @atemate

## Other Changes

* refactor: rename flavor to overlay across the codebase (#233) @atemate
* feat(crew): built-in persistence flavors for checkpointer (debt/1k5a8e) (#224) @atemate
* test(flow): ADK LLM Auditor compilation and execution tests (#219) @atemate
* docs: update CHANGELOG.md for v0.5.1 and v0.5.2 (#231) @[github-actions[bot]](https://github.com/apps/github-actions)
* fix(release): use local URLs in helm index for playground dep build (#232) @atemate

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
  --version 0.5.3 \
  --namespace asya-system \
  --create-namespace
helm install asya-gateway asya/asya-gateway \
  --version 0.5.3 \
  --namespace asya
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-crew:0.5.3`
- `ghcr.io/deliveryhero/asya-gateway:0.5.3`
- `ghcr.io/deliveryhero/asya-injector:0.5.3`
- `ghcr.io/deliveryhero/asya-sidecar:0.5.3`
- `ghcr.io/deliveryhero/asya-testing:0.5.3`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)




## [0.5.2] - 2026-02-27

## Major Changes

* feat: scaffold asya-lab and asya-ui packages, reserve image names (#229) @atemate
* fix(compiler): fix errors in compiler, while-loop visualization and DOT simplifications (#226) @atemate
* fix: Fix e2e failures on main branch (#223) @atemate
* feat(crew): x-pause and x-resume crew actors (Phase B, epic 1ixy) (#221) @atemate
* feat: pause/resume/cancel lifecycle for A2A protocol (Phase A, epic 1ixy) (#222) @atemate
* fix: Fix e2e failures on main branch for fanout (#218) @atemate
* feat(gateway): stamp status.deadline\_at in message protocol (wave 3, epic 1crv) (#215) @atemate
* feat(sidecar): SLA enforcement and effective timeout (wave 2, epic 1crv) (#214) @atemate
* refactor!: replace envelope terminology with message/msg across codebase (#213) @atemate
* feat(sidecar): add DeadlineAt field and per-call timeout (wave 1, epic 1crv) (#212) @atemate
* test: integration tests for streaming partial events (epic 1ia4) (#209) @atemate
* feat(integration): fan-out/fan-in integration test suite (epic 1c7i) (#211) @atemate
* feat(runtime): add open(path, x) exclusive create mode for state proxy (epic 1c7i) (#206) @atemate
* feat(runtime): SSE streaming protocol for generator handlers (epic 1ia4) (#205) @atemate
* feat(gateway): A2A protocol compliance - core endpoints (epic 1c0d) (#202) @atemate
* feat(sidecar): x-asya-route-override header resolution (epic 1crb) (#201) @atemate
* feat(runtime): add async generator handler support (epic 1ia4) (#203) @atemate
* feat(1dmf): add state proxy connectors — s3-passthrough, s3-buffered-cas, redis-buffered-cas (#200) @atemate
* feat(runtime): replace ASYA\_HANDLER\_MODE with /proc/asya/msg/ VFS (epic 1ixt) (#198) @atemate
* feat(1c4w): E2E flavor testing — EnvironmentConfigs, actor migration, compositionSelector (#197) @atemate
* feat(fanout): fan-out/fan-in infrastructure (epic 1c7i) (#196) @atemate
* feat: add stateful actors via state proxy sidecars (epic 1dmf) (#195) @atemate

## Other Changes

* feat: scaffold asya-lab and asya-ui packages, reserve image names (#229) @atemate
* fix(compiler): fix errors in compiler, while-loop visualization and DOT simplifications (#226) @atemate
* test(integration): SLA enforcement tests across sidecar, runtime, and gateway (#228) @atemate
* docs: task pause/resume feature documentation (#227) @atemate
* test(integration): pause/resume flow end-to-end (epic 1ixy) (#225) @atemate
* fix: Fix e2e failures on main branch (#223) @atemate
* test(component): sidecar SLA enforcement tests (wave 4, epic 1crv) (#220) @atemate
* feat(crew): x-pause and x-resume crew actors (Phase B, epic 1ixy) (#221) @atemate
* feat: pause/resume/cancel lifecycle for A2A protocol (Phase A, epic 1ixy) (#222) @atemate
* refactor(crew): migrate S3 checkpointer to state-proxy-based file I/O (task 1k34nz) (#216) @atemate
* fix: Fix e2e failures on main branch for fanout (#218) @atemate
* feat(gateway): stamp status.deadline\_at in message protocol (wave 3, epic 1crv) (#215) @atemate
* feat(sidecar): SLA enforcement and effective timeout (wave 2, epic 1crv) (#214) @atemate
* refactor!: replace envelope terminology with message/msg across codebase (#213) @atemate
* feat(sidecar): add DeadlineAt field and per-call timeout (wave 1, epic 1crv) (#212) @atemate
* test: integration tests for streaming partial events (epic 1ia4) (#209) @atemate
* test(e2e): compiled flow with fan-out/fan-in on Kind cluster (epic 1c7i) (#210) @atemate
* test(state-proxy): state proxy architecture doc and error path tests (epic 1dmf) (#207) @atemate
* feat(integration): fan-out/fan-in integration test suite (epic 1c7i) (#211) @atemate
* feat(runtime): add open(path, x) exclusive create mode for state proxy (epic 1c7i) (#206) @atemate
* refactor: replace envelope terminology with task/VFS (epic 1c0d) (#208) @atemate
* feat(runtime): SSE streaming protocol for generator handlers (epic 1ia4) (#205) @atemate
* test(state-proxy): component tests for state proxy + fix S3 passthrough write (epic 1dmf) (#204) @atemate
* feat(gateway): A2A protocol compliance - core endpoints (epic 1c0d) (#202) @atemate
* feat(sidecar): x-asya-route-override header resolution (epic 1crb) (#201) @atemate
* feat(runtime): add async generator handler support (epic 1ia4) (#203) @atemate
* feat(1dmf): add state proxy connectors — s3-passthrough, s3-buffered-cas, redis-buffered-cas (#200) @atemate
* feat(runtime): replace ASYA\_HANDLER\_MODE with /proc/asya/msg/ VFS (epic 1ixt) (#198) @atemate
* feat(1c4w): E2E flavor testing — EnvironmentConfigs, actor migration, compositionSelector (#197) @atemate
* feat(fanout): fan-out/fan-in infrastructure (epic 1c7i) (#196) @atemate
* feat: add stateful actors via state proxy sidecars (epic 1dmf) (#195) @atemate

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
  --version 0.5.2 \
  --namespace asya-system \
  --create-namespace
helm install asya-gateway asya/asya-gateway \
  --version 0.5.2 \
  --namespace asya
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-crew:0.5.2`
- `ghcr.io/deliveryhero/asya-gateway:0.5.2`
- `ghcr.io/deliveryhero/asya-injector:0.5.2`
- `ghcr.io/deliveryhero/asya-sidecar:0.5.2`
- `ghcr.io/deliveryhero/asya-testing:0.5.2`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)



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
kubectl apply -f https://github.com/deliveryhero/asya/releases/download/0.4.0/asya-crds.yaml
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
  --version 0.4.0 \
  --namespace asya-system \
  --create-namespace
```

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.4.0`
- `ghcr.io/deliveryhero/asya-gateway:0.4.0`
- `ghcr.io/deliveryhero/asya-sidecar:0.4.0`
- `ghcr.io/deliveryhero/asya-crew:0.4.0`
- `ghcr.io/deliveryhero/asya-testing:0.4.0`

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

- `ghcr.io/deliveryhero/asya-operator:0.3.0`
- `ghcr.io/deliveryhero/asya-gateway:0.3.0`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.0`
- `ghcr.io/deliveryhero/asya-crew:0.3.0`
- `ghcr.io/deliveryhero/asya-testing:0.3.0`

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


[0.5.1]: https://github.com/deliveryhero/asya/releases/tag/v0.5.1


[0.5.2]: https://github.com/deliveryhero/asya/releases/tag/v0.5.2


[0.5.3]: https://github.com/deliveryhero/asya/releases/tag/v0.5.3


[0.5.4]: https://github.com/deliveryhero/asya/releases/tag/v0.5.4


[0.5.5]: https://github.com/deliveryhero/asya/releases/tag/v0.5.5


[0.5.7]: https://github.com/deliveryhero/asya/releases/tag/v0.5.7


[0.5.8]: https://github.com/deliveryhero/asya/releases/tag/v0.5.8


[0.5.9]: https://github.com/deliveryhero/asya/releases/tag/v0.5.9


[0.5.10]: https://github.com/deliveryhero/asya/releases/tag/v0.5.10


[0.5.11]: https://github.com/deliveryhero/asya/releases/tag/v0.5.11


[0.5.12]: https://github.com/deliveryhero/asya/releases/tag/v0.5.12


[0.5.13]: https://github.com/deliveryhero/asya/releases/tag/v0.5.13


[0.5.14]: https://github.com/deliveryhero/asya/releases/tag/v0.5.14


[0.5.15]: https://github.com/deliveryhero/asya/releases/tag/v0.5.15


[0.5.16]: https://github.com/deliveryhero/asya/releases/tag/v0.5.16


[1.0.1]: https://github.com/deliveryhero/asya/releases/tag/v1.0.1


[1.0.2]: https://github.com/deliveryhero/asya/releases/tag/v1.0.2


[1.0.3]: https://github.com/deliveryhero/asya/releases/tag/v1.0.3

[1.0.4]: https://github.com/deliveryhero/asya/releases/tag/v1.0.4

[1.0.5]: https://github.com/deliveryhero/asya/releases/tag/v1.0.5

[1.0.6]: https://github.com/deliveryhero/asya/releases/tag/v1.0.6

[1.0.7]: https://github.com/deliveryhero/asya/releases/tag/v1.0.7

[1.0.8]: https://github.com/deliveryhero/asya/releases/tag/v1.0.8

[1.0.9]: https://github.com/deliveryhero/asya/releases/tag/v1.0.9


[1.1.0]: https://github.com/deliveryhero/asya/releases/tag/v1.1.0


[Unreleased]: https://github.com/deliveryhero/asya/compare/v1.1.2...HEAD
[1.1.2]: https://github.com/deliveryhero/asya/releases/tag/v1.1.2

