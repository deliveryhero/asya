git-aint state | 2026-04-24T08:34:19Z

Working(11) Open(141) Closed(379)

[dvgpp] "split helm image values into repository+tag"  P2 working
  .aint/active/aint.split-helm-image-values-into-repository-tag.dvgpp.md

[7lh94] "merge asya-samples into examples/end-to-end/monorepo"  P2 working
  .aint/active/aint.merge-asya-samples-into-examples-end-to-end.7lh94.md

[c7mnc] "Gateway chart: s3/gcs backend for mesh state proxy, update e2e profiles"  P2 working
  .aint/active/aint.mesh-state-proxy-backends.c7mnc.md

[okw15] "Consolidate state proxy images: asya-state-proxy-py and asya-state-proxy-go"  P2 working
  .aint/active/aint.state-proxy-images.okw15.md

[n6g6h] "asya-lab"  P2 working  [2/14 done]
  .aint/active/aint.asya-lab.n6g6h/ adr.click-over-argparse.md, adr.compiler-template-not-helm.md, adr.ds-config-management-research.md, adr.k-d-command-split.md, adr.kustomize-not-extra-dependency.md, adr.no-cog.md, conversation-tilt.txt, refactor-config-with-templates.md, research-build-system.md, research-compiler-knowledge-base.md, research-compiler-resolution.md, research-config-setup.md, research-no-dockerfile.md, research-seamless-build.md, rfc-ui-components.md, rfc.md
  ├── [assek] "Document skaffold as Python source resolver for compile-time imports"  open
  ├── [6wvo1] "Adapt compiler for asya-lab flows"  open
  ├── [i6o8a] "Phase 5: Docker Compose CLI + socket transport"  working
  ├── [3qmnw] "Improve XR handler syntax: support file.py:function format for explicit handler resolution"  open
  ├── [eysnv] "Compiler: context-aware while loop exit (preserve route.next for composability)"  open
  ├── [pfbxg] "Minor code review comments"  open
  ├── [ppsug] "Compiler: prevent shared base/ dir when stamping manifests without project config"  open
  ├── [v9nm3] "Adapt e2e flow tests to use asya-lab CLI for compilation instead of hand-crafted Helm charts"  open
  ├── [e4u90] "Phase 6: @asya/ui React components + asya serve + Jupyter widget"  working
  ├── [c80q9] "Compiler: support # asya: actor directive on imported function definitions"  open
  ├── [bggre] "ConfigMap-mount single-file actors (no custom image)"  open
  ├── [8su9b] "Add socket transport component test suite"  open
  ├── [xnwlj] "Restructure examples: teaser in asya, full samples in asya-samples"  merged
  └── [vppe7] "Hands-on demo: Skaffold vs Tilt for multi-team actor repos"  rejected

[00000] "Miscellaneous"  P2 working  [1/25 done]
  .aint/active/aint.miscellaneous.00000/
  ├── [1fqon] "Add Asya-level runtime metrics via response JSON"  open
  ├── [atewx] "Research: SOCI/Stargz lazy image loading for scale-to-zero with large ML images"  open
  ├── [1fx95] "Research AGNTCY protocol feasibility for Asya Gateway"  open
  ├── [1lnzc] "Post-compilation invariant checks: all routers visible in DOT with proper connectivity"  open
  ├── [1fzx5] "Auto-detect runtime container instead of requiring asya-runtime name"  open
  ├── [1qey0] "Flow DSL: support local variable assignments from state accessors"  open
  ├── [1fvmw] "Research: HolmesGPT for AI-assisted Asya debugging"  open
  ├── [1m1vg] "Fix test_asyncactor_label_propagation: update assertions to match Crossplane labeling"  open
  ├── [oz2o7] "E2E: fix gateway restart timing in test_gateway_restart_during_processing"  open
  ├── [wkv3k] "OAuth 2.1 scope enforcement per MCP endpoint (post-v0)"  open
  ├── [tlu5q] "Migrate XRD from apiextensions.crossplane.io/v1 to v2"  open
  ├── [1ip8k] "Implement nats-kv-buffered-cas connector"  open
  ├── [h6h2z] "Configure DLQ redrive policy in Crossplane compositions"  open
  ├── [vp72j] "Upgrade Go toolchain to 1.25 (CVE-2026-25679, CVE-2026-27139, CVE-2026-27142)"  open
  ├── [1jhl4] "Integration test: verify exponential backoff delays grow geometrically"  open
  ├── [1folc] "Research: Actor warm-up pattern before scale-to-zero"  open
  ├── [ws0sy] "scaler-pubsub: handle DeadlineExceeded as empty queue"  working
  ├── [aljc8] "docs: actor flavors tutorial"  working
  ├── [1fswe] "Implement load testing suite for operator reconciliation and actor autoscaling"  open
  ├── [d2h77] "feat(sidecar): support ASYA_BASE_PREFIX for single-gateway deployments with URL prefix"  open
  ├── [1f1sh] "(EPIC) Enable workloadRef: Bring Your Own Deployment"  open
  ├── [zlsem] "fix(sidecar): strip trailing slash from gatewayURL in NewReporter"  open
  ├── [1fvxp] "Enhance AGENTS.md with decision trees for faster agent comprehension"  open
  ├── [1j0yi] "Gateway: remove queue-name fallback once status.phase is stable"  open
  └── [w5tgs] "Shorten default kubectl get asya view"  merged

[2dich] "Go GCS-backed state proxy (gcs-kv) with DuckDB /query — mirrors s3kv"  P2 open  (recently modified)
  .aint/active/aint.gcs-kv.2dich.md

[ezpsa] "Observability init"  P2 working  [0/2]
  .aint/active/aint.observability-init.ezpsa/ rfc.md
  ├── [n84dj] "Retry delay observability: per-retry-event metrics and logging"  open
  └── [1f4gd] "Configure OTEL env vars for user metrics in runtime container"  open

[8v7o0] "autoresearch"  P2 open  (recently modified)
  .aint/active/aint.autoresearch.8v7o0/ adr.compiled-flow-not-free-routing-actor.md, adr.dual-mount-same-backend.md, adr.git-state-proxy-over-git-sync.md, adr.rl-framing-for-experiment-loop.md, design.dataset-state-proxy.md, rfc.md

[63keu] "RFC: Replace asya-gateway with asya-mesh-api + protocol adapters"  P1 open

[emmc5] "Implement A2A protocol"  P2 open

[fd73j] "Actor Warm-Up Pattern for Scale-to-Zero Validation"  P2 open

[0yjeo] "agentic-claw-code"  P2 open

[00001] "Tech debt"  P2 open

[pj0fo] "compiler-simplify"  P2 open

[7b55c] "Agentic - Umbrella"  P2 open

[ob6f9] "Asya Lens: Self-Hosted Dashboard and IDE"  P2 open

[ty5he] "Typed Handler Signatures"  P2 open

[kchkv] "Agentic security"  P2 open

[kzy6w] "Gateway rearchitect debt"  P3 open

15 open aints not shown (git aint get)

Closed(5):
[i0ewl] "PR5: DuckDB /query for S3/GCS Python state proxy connectors"  merged
[mtlj2] "Fix flaky SLA integration test (sidecar-runtime rabbitmq)"  merged
[1frc7] "Implement 01-single-agent: OpenAI Agents SDK"  merged
[1fzhp] "Research: kubectl-asya via Krew vs custom CLI wrapper"  rejected
[1frs7] "XRD: Add spec.flavors field to AsyncActor"  merged
... and 374 more
