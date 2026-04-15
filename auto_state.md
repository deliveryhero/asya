git-aint state | 2026-04-15T08:20:53Z

Working(8) Open(132) Closed(367)

[00000] "Miscellaneous"  P2 working  [0/25]
  .aint/active/aint.miscellaneous.00000/
  ├── [1fswe] "Implement load testing suite for operator reconciliation and actor autoscaling"  open
  ├── [1fqon] "Add Asya-level runtime metrics via response JSON"  open
  ├── [1fx95] "Research AGNTCY protocol feasibility for Asya Gateway"  open
  ├── [d2h77] "feat(sidecar): support ASYA_BASE_PREFIX for single-gateway deployments with URL prefix"  open
  ├── [oz2o7] "E2E: fix gateway restart timing in test_gateway_restart_during_processing"  open
  ├── [aljc8] "docs: actor flavors tutorial"  working
  ├── [1fvmw] "Research: HolmesGPT for AI-assisted Asya debugging"  open
  ├── [1lnzc] "Post-compilation invariant checks: all routers visible in DOT with proper connectivity"  open
  ├── [wkv3k] "OAuth 2.1 scope enforcement per MCP endpoint (post-v0)"  open
  ├── [1j0yi] "Gateway: remove queue-name fallback once status.phase is stable"  open
  ├── [zlsem] "fix(sidecar): strip trailing slash from gatewayURL in NewReporter"  open
  ├── [h6h2z] "Configure DLQ redrive policy in Crossplane compositions"  open
  ├── [1m1vg] "Fix test_asyncactor_label_propagation: update assertions to match Crossplane labeling"  open
  ├── [1fvxp] "Enhance AGENTS.md with decision trees for faster agent comprehension"  open
  ├── [tlu5q] "Migrate XRD from apiextensions.crossplane.io/v1 to v2"  open
  ├── [1f1sh] "(EPIC) Enable workloadRef: Bring Your Own Deployment"  open
  ├── [1fzx5] "Auto-detect runtime container instead of requiring asya-runtime name"  open
  ├── [1folc] "Research: Actor warm-up pattern before scale-to-zero"  open
  ├── [vp72j] "Upgrade Go toolchain to 1.25 (CVE-2026-25679, CVE-2026-27139, CVE-2026-27142)"  open
  ├── [1qey0] "Flow DSL: support local variable assignments from state accessors"  open
  ├── [1jhl4] "Integration test: verify exponential backoff delays grow geometrically"  open
  ├── [ws0sy] "scaler-pubsub: handle DeadlineExceeded as empty queue"  working
  ├── [1ip8k] "Implement nats-kv-buffered-cas connector"  open
  ├── [atewx] "Research: SOCI/Stargz lazy image loading for scale-to-zero with large ML images"  open
  └── [w5tgs] "Shorten default kubectl get asya view"  pushed

[n6g6h] "asya-lab"  P2 working  [1/14 done]
  .aint/active/aint.asya-lab.n6g6h/ adr.click-over-argparse.md, adr.compiler-template-not-helm.md, adr.ds-config-management-research.md, adr.k-d-command-split.md, adr.kustomize-not-extra-dependency.md, adr.no-cog.md, conversation-tilt.txt, refactor-config-with-templates.md, research-build-system.md, research-compiler-knowledge-base.md, research-compiler-resolution.md, research-config-setup.md, research-no-dockerfile.md, research-seamless-build.md, rfc-ui-components.md, rfc.md
  ├── [bggre] "ConfigMap-mount single-file actors (no custom image)"  open
  ├── [eysnv] "Compiler: context-aware while loop exit (preserve route.next for composability)"  open
  ├── [6wvo1] "Adapt compiler for asya-lab flows"  open
  ├── [ppsug] "Compiler: prevent shared base/ dir when stamping manifests without project config"  open
  ├── [i6o8a] "Phase 5: Docker Compose CLI + socket transport"  working
  ├── [c80q9] "Compiler: support # asya: actor directive on imported function definitions"  open
  ├── [e4u90] "Phase 6: @asya/ui React components + asya serve + Jupyter widget"  working
  ├── [8su9b] "Add socket transport component test suite"  open
  ├── [pfbxg] "Minor code review comments"  open
  ├── [vppe7] "Hands-on demo: Skaffold vs Tilt for multi-team actor repos"  working
  ├── [assek] "Document skaffold as Python source resolver for compile-time imports"  open
  ├── [3qmnw] "Improve XR handler syntax: support file.py:function format for explicit handler resolution"  open
  ├── [v9nm3] "Adapt e2e flow tests to use asya-lab CLI for compilation instead of hand-crafted Helm charts"  open
  └── [xnwlj] "Restructure examples: teaser in asya, full samples in asya-samples"  merged

[ezpsa] "Observability init"  P2 working  [0/2]
  .aint/active/aint.observability-init.ezpsa/ rfc.md
  ├── [n84dj] "Retry delay observability: per-retry-event metrics and logging"  open
  └── [1f4gd] "Configure OTEL env vars for user metrics in runtime container"  open

[63keu] "RFC: Replace asya-gateway with agentgateway + asya-dispatcher"  P1 open  (recently modified)
  .aint/active/aint.gateway-rearchitect.63keu/ rfc.md

[00001] "Tech debt"  P2 open  (recently modified)
  .aint/active/aint.tech-debt.00001/

[pj0fo] "compiler-simplify"  P2 open  (recently modified)
  .aint/active/aint.compiler-simplify.pj0fo/ design-decisions.md, rfc.md

[8v7o0] "autoresearch"  P2 open  (recently modified)
  .aint/active/aint.autoresearch.8v7o0/ adr.compiled-flow-not-free-routing-actor.md, adr.dual-mount-same-backend.md, adr.git-state-proxy-over-git-sync.md, adr.rl-framing-for-experiment-loop.md, design.dataset-state-proxy.md, rfc.md

[emmc5] "Implement A2A protocol"  P2 open  (recently modified)
  .aint/active/aint.implement-a2a-protocol.emmc5/ adr.configmap-flow-registry.md, impl-phases.md, rfc.md

[9v62d] "Message Serialization Optimization"  P2 open  (recently modified)
  .aint/active/aint.message-serialization-optimization.9v62d/

[7b55c] "Agentic - Umbrella"  P2 open  (recently modified)
  .aint/active/aint.agentic-umbrella.7b55c/ adr.asya-csp-vs-adk-async-generator-for-agentic.md, night-thoughts.md, survey-adk-data-flow.md, survey-agentic-frameworks.md

[fd73j] "Actor Warm-Up Pattern for Scale-to-Zero Validation"  P2 open  (recently modified)
  .aint/active/aint.actor-warm-up-pattern-for-scale-to-zero-validation.fd73j.md

[enren] "Design workflow for asya flows"  P2 open  (recently modified)
  .aint/active/aint.design-workflow-for-asya-flows.enren/ adr-async-flow-crd-vs-labels.md

[ty5he] "Typed Handler Signatures"  P2 open  (recently modified)
  .aint/active/aint.typed-handler-signatures.ty5he/ impl-phases.md, rfc.md

[mxzgo] "Flow DSL Free Variables and Iteration"  P2 open  (recently modified)
  .aint/active/aint.flow-dsl-free-variables-and-iteration.mxzgo/ rfc.md

[2w664] "A/B/N Traffic Routing for Actor Pipelines"  P2 open  (recently modified)
  .aint/active/aint.abn-traffic-routing-for-actor-pipelines.2w664/ rfc.md

[34xba] "Timeouts: per-actor and per-flow"  P2 open  (recently modified)
  .aint/active/aint.timeouts-per-actor-and-per-flow.34xba/ impl-phases.md, rfc.md

[kchkv] "Agentic security"  P2 open  (recently modified)
  .aint/active/aint.agentic-security.kchkv/ research-a2a-auth.md, research-mcp-auth.md, rfc.md

[l899s] "New transports"  P2 open  (recently modified)
  .aint/active/aint.new-transports.l899s/ claude.pubsub-vs-nats-vs-strimzi.txt

[1fkil] "Research: Adapt Gateway API to A2A/ACP/A2UI standards"  P3 open  (recently modified)
  .aint/archive/aint.research-adapt-gateway-api-a2a-acp-a2ui-standards.1fkil.md

[1f53y] "Implement push notification configuration endpoints"  P4 open  (recently modified)
  .aint/archive/aint.implement-push-notification-configuration-endpoints.1f53y.md

9 open aints not shown (git aint get)

Closed(5):
[ldx4p] "Enable Observability for KubeCon Demo"  merged
[1ftxe] "Flow DSL: Support async/await, loops, and try-catch"  merged
[1fj66] "Transport: add SendWithDelay() and rename Nack() to Requeue()"  merged
[8ctgi] "Update existing flow examples and tests for new compiler pipeline"  rejected
[tj91u] "design+impl: replace nonRetryableErrors with errorRoutes in resiliency config"  rejected
... and 362 more
