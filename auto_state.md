git-aint state | 2026-04-24T10:34:53Z

Working(10) Open(142) Closed(380)

[7lh94] "merge asya-samples into examples/end-to-end/monorepo"  P2 working
  .aint/active/aint.merge-asya-samples-into-examples-end-to-end.7lh94.md

[okw15] "Consolidate state proxy images: asya-state-proxy-py and asya-state-proxy-go"  P2 working
  .aint/active/aint.state-proxy-images.okw15.md

[c7mnc] "Gateway chart: s3/gcs backend for mesh state proxy, update e2e profiles"  P2 working
  .aint/active/aint.mesh-state-proxy-backends.c7mnc.md

[2dich] "Go GCS-backed state proxy (gcs-kv) with DuckDB /query — mirrors s3kv"  P2 open  (recently modified)
  .aint/active/aint.gcs-kv.2dich.md

[n6g6h] "asya-lab"  P2 working  [2/14 done]
  .aint/active/aint.asya-lab.n6g6h/ adr.click-over-argparse.md, adr.compiler-template-not-helm.md, adr.ds-config-management-research.md, adr.k-d-command-split.md, adr.kustomize-not-extra-dependency.md, adr.no-cog.md, conversation-tilt.txt, refactor-config-with-templates.md, research-build-system.md, research-compiler-knowledge-base.md, research-compiler-resolution.md, research-config-setup.md, research-no-dockerfile.md, research-seamless-build.md, rfc-ui-components.md, rfc.md
  ├── [e4u90] "Phase 6: @asya/ui React components + asya serve + Jupyter widget"  working
  ├── [6wvo1] "Adapt compiler for asya-lab flows"  open
  ├── [ppsug] "Compiler: prevent shared base/ dir when stamping manifests without project config"  open
  ├── [bggre] "ConfigMap-mount single-file actors (no custom image)"  open
  ├── [v9nm3] "Adapt e2e flow tests to use asya-lab CLI for compilation instead of hand-crafted Helm charts"  open
  ├── [eysnv] "Compiler: context-aware while loop exit (preserve route.next for composability)"  open
  ├── [c80q9] "Compiler: support # asya: actor directive on imported function definitions"  open
  ├── [8su9b] "Add socket transport component test suite"  open
  ├── [pfbxg] "Minor code review comments"  open
  ├── [i6o8a] "Phase 5: Docker Compose CLI + socket transport"  working
  ├── [assek] "Document skaffold as Python source resolver for compile-time imports"  open
  ├── [3qmnw] "Improve XR handler syntax: support file.py:function format for explicit handler resolution"  open
  ├── [vppe7] "Hands-on demo: Skaffold vs Tilt for multi-team actor repos"  rejected
  └── [xnwlj] "Restructure examples: teaser in asya, full samples in asya-samples"  merged

[00000] "Miscellaneous"  P2 working  [1/25 done]
  .aint/active/aint.miscellaneous.00000/
  ├── [1lnzc] "Post-compilation invariant checks: all routers visible in DOT with proper connectivity"  open
  ├── [atewx] "Research: SOCI/Stargz lazy image loading for scale-to-zero with large ML images"  open
  ├── [aljc8] "docs: actor flavors tutorial"  working
  ├── [tlu5q] "Migrate XRD from apiextensions.crossplane.io/v1 to v2"  open
  ├── [1fswe] "Implement load testing suite for operator reconciliation and actor autoscaling"  open
  ├── [1fzx5] "Auto-detect runtime container instead of requiring asya-runtime name"  open
  ├── [1qey0] "Flow DSL: support local variable assignments from state accessors"  open
  ├── [vp72j] "Upgrade Go toolchain to 1.25 (CVE-2026-25679, CVE-2026-27139, CVE-2026-27142)"  open
  ├── [zlsem] "fix(sidecar): strip trailing slash from gatewayURL in NewReporter"  open
  ├── [ws0sy] "scaler-pubsub: handle DeadlineExceeded as empty queue"  working
  ├── [1f1sh] "(EPIC) Enable workloadRef: Bring Your Own Deployment"  open
  ├── [wkv3k] "OAuth 2.1 scope enforcement per MCP endpoint (post-v0)"  open
  ├── [1jhl4] "Integration test: verify exponential backoff delays grow geometrically"  open
  ├── [1folc] "Research: Actor warm-up pattern before scale-to-zero"  open
  ├── [1fx95] "Research AGNTCY protocol feasibility for Asya Gateway"  open
  ├── [1fvxp] "Enhance AGENTS.md with decision trees for faster agent comprehension"  open
  ├── [1fvmw] "Research: HolmesGPT for AI-assisted Asya debugging"  open
  ├── [1ip8k] "Implement nats-kv-buffered-cas connector"  open
  ├── [d2h77] "feat(sidecar): support ASYA_BASE_PREFIX for single-gateway deployments with URL prefix"  open
  ├── [oz2o7] "E2E: fix gateway restart timing in test_gateway_restart_during_processing"  open
  ├── [h6h2z] "Configure DLQ redrive policy in Crossplane compositions"  open
  ├── [1m1vg] "Fix test_asyncactor_label_propagation: update assertions to match Crossplane labeling"  open
  ├── [1j0yi] "Gateway: remove queue-name fallback once status.phase is stable"  open
  ├── [1fqon] "Add Asya-level runtime metrics via response JSON"  open
  └── [w5tgs] "Shorten default kubectl get asya view"  merged

[8v7o0] "autoresearch"  P2 open  (recently modified)
  .aint/active/aint.autoresearch.8v7o0/ adr.compiled-flow-not-free-routing-actor.md, adr.dual-mount-same-backend.md, adr.git-state-proxy-over-git-sync.md, adr.rl-framing-for-experiment-loop.md, design.dataset-state-proxy.md, rfc.md

[ob6f9] "Asya Lens: Self-Hosted Dashboard and IDE"  P2 open

[pj0fo] "compiler-simplify"  P2 open

[akgyg] "E2E rabbitmq-minio: Crossplane Requirements API race blocks flavored actors"  P2 open

[fd73j] "Actor Warm-Up Pattern for Scale-to-Zero Validation"  P2 open

[hb1v1] "Local testing workflow in docker-compose"  P2 open

[0yjeo] "agentic-claw-code"  P2 open

[63keu] "RFC: Replace asya-gateway with asya-mesh-api + protocol adapters"  P1 open

[1fw7s] "Implement AG-UI event streaming endpoint"  P2 open

[1f7aw] "Implement input_required state for human-in-the-loop"  P2 open

[1f53y] "Implement push notification configuration endpoints"  P4 open

[1fgyz] "Add A2UI payload support (optional)"  P4 open

[1foq3] "Add gRPC transport support"  P3 open

[1fgex] "Implement GET /tasks endpoint (list tasks)"  P3 open

14 open aints not shown (git aint get)

Closed(5):
[bvs44] "fix(flow-compiler): generate SVG instead of PNG to eliminate non-deterministic pre-commit regeneration"  merged
[oihm2] "Unify terminology: task=A2A, tool=MCP, envelope=mesh"  merged
[1f2ww] "Runtime: AsyncGenerator handler support"  merged
[1fw74] "Sidecar: multi-frame streaming protocol (runtime <-> sidecar)"  rejected
[1fld6] "Clean up build system, CI pipelines, and documentation after operator removal"  merged
... and 375 more
