git-aint state | 2026-04-14T19:18:16Z

Working(10) Open(122) Closed(365)

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

[00000] "Miscellaneous"  P2 working  [0/26]
  .aint/active/aint.miscellaneous.00000/
  ├── [1fswe] "Implement load testing suite for operator reconciliation and actor autoscaling"  open
  ├── [gvqck] "GKE demo cluster + docs: KubeCon GCP Pub/Sub deployment"  working
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

[ezpsa] "Observability init"  P2 working  [0/3]
  .aint/active/aint.observability-init.ezpsa/ rfc.md
  ├── [ldx4p] "Enable Observability for KubeCon Demo"  working
  ├── [n84dj] "Retry delay observability: per-retry-event metrics and logging"  open
  └── [1f4gd] "Configure OTEL env vars for user metrics in runtime container"  open

[63keu] "RFC: Replace asya-gateway with agentgateway + asya-dispatcher"  P1 open
  .aint/active/aint.gateway-rearchitect.63keu/ rfc.md

[00001] "Tech debt"  P2 open  [0/31]
  .aint/active/aint.tech-debt.00001/
  ├── [jj4of] "SQS delay chaining for retry backoffs exceeding 15-minute cap"  open
  ├── [pw0jj] "XRD: Add comprehensive CEL validation for workload schema"  open
  ├── [1msun] "Support kubectl logs asya/actor-name"  open
  ├── [2k242] "Evaluate LocalStack alternatives or upgrade path for auth-required versions"  open
  ├── [1f7wi] "Refactor: Unify injected mounts under /opt/asya directory"  open
  ├── [1fwaa] "Runtime 'Client disconnected' warnings in crew actors"  open
  ├── [ah8o4] "Gateway: use MCP structuredContent and A2A DataPart for final payload"  open
  ├── [ts8ha] "A2A gateway: parse JSON text parts into payload keys"  open
  ├── [1omcl] "Support del statement as payload mutation"  open
  ├── [hvk0d] "Support handler-driven retry delay (Retry-After from handler)"  open
  ├── [5ttg4] "Support per-error-type retry counts in resiliency config"  open
  ├── [o2b6b] "Deploy Tempo in monitoring namespace instead of user namespace"  open
  ├── [xcd1s] "Implement circuit breaker in sidecar (Dapr-inspired, CEL trip expressions)"  open
  ├── [ez342] "asya k apply: add --prune support for auto-deleting stale actors"  open
  ├── [pe83q] "Fix flaky test_slow_actor_exceeds_sla SLA test in CI"  open
  ├── [1oa6z] "Support match statement as conditional routing"  open
  ├── [fba44] "Gateway: cascading error hides root cause when skill not found"  open
  ├── [1fm8l] "Add load test Job to asya-quickstart chart"  open
  ├── [jgwnk] "Support namespace-scoped flavors via ConfigMaps"  open
  ├── [1facb] "Sidecar: ASYA_ACTOR_ROLE (regular|sink|sump) and ASYA_ACTOR_SINK unification"  open
  ├── [r2brm] "Rate limiting for outbound handler calls in sidecar"  open
  ├── [pwx66] "Crossplane queue health monitoring: operator queue recreation not applicable"  open
  ├── [56o1e] "CI gateway (sqs) component tests fail with disk space exhaustion"  open
  ├── [1phpj] "Design SendWithDelay crew actor for transports without native delay"  open
  ├── [1k1bx] "Merge asya-dlq-worker image into asya-crew (multi-stage build, shared image with command override)"  open
  ├── [6e74y] "Add resiliency EnvironmentConfig flavor examples"  open
  ├── [1ffp2] "Add helm template validation to pre-commit hooks"  open
  ├── [1jqks] "x-sump: emit OpenTelemetry metrics for hook outcomes"  open
  ├── [a38so] "OpenTelemetry tracing: sidecar spans, runtime spans, asya k trace CLI"  open
  ├── [4d6ze] "CLI security: validate URLs and subprocess args from user config"  open
  └── [dxo1d] "Simplify component/integration tests: unix socket transport + local FS storage"  open

[pj0fo] "compiler-simplify"  P2 open
  .aint/active/aint.compiler-simplify.pj0fo/ design-decisions.md, rfc.md

[ob6f9] "Asya Lens: Self-Hosted Dashboard and IDE"  P2 open
  .aint/active/aint.asya-lens-self-hosted-dashboard-and-ide.ob6f9/ rfc.md

[emmc5] "Implement A2A protocol"  P2 open  [0/2]
  .aint/active/aint.implement-a2a-protocol.emmc5/ adr.configmap-flow-registry.md, impl-phases.md, rfc.md
  ├── [82bdw] "x-pause: auto-preserve remaining route.next when actor overwrites with x-pause"  open
  └── [8sc0k] "Check GetTasks Implementation"  open

[9v62d] "Message Serialization Optimization"  P2 open  [0/1]
  .aint/active/aint.message-serialization-optimization.9v62d/
  └── [1f9av] "Add optional zlib compression for large envelopes"  open

[7b55c] "Agentic - Umbrella"  P2 open  [0/5]
  .aint/active/aint.agentic-umbrella.7b55c/ adr.asya-csp-vs-adk-async-generator-for-agentic.md, night-thoughts.md, survey-adk-data-flow.md, survey-agentic-frameworks.md
  ├── [1m0e2] "Escalation action for actor-driven loop termination"  open
  ├── [1faqh] "Map Asya events to AG-UI event types"  open
  ├── [1f7my] "Scheduled trigger crew actors (CronJob-based delay for transports without SendWithDelay)"  open
  ├── [1m0f8] "Research: before/after callbacks for model and tool interceptors"  open
  └── [1m0gs] "Research: event compaction and context window management for long-running agents"  open

[0yjeo] "agentic-claw-code"  P2 open
  .aint/active/aint.agentic-claw-code.0yjeo/ session-asya-vs-openclaw.md

[fd73j] "Actor Warm-Up Pattern for Scale-to-Zero Validation"  P2 open
  .aint/active/aint.actor-warm-up-pattern-for-scale-to-zero-validation.fd73j.md

[enren] "Design workflow for asya flows"  P2 open  [0/3]
  .aint/active/aint.design-workflow-for-asya-flows.enren/ adr-async-flow-crd-vs-labels.md
  ├── [1fbwb] "Phase 3: Fully active AsyncFlow via custom Crossplane composition function"  open
  ├── [1fbqd] "Phase 2: Semi-active AsyncFlow via function-extra-resources"  open
  └── [1fnb9] "Phase 1: Passive AsyncFlow XRD with mixed ownership model"  open

[ty5he] "Typed Handler Signatures"  P2 open  [0/6]
  .aint/active/aint.typed-handler-signatures.ty5he/ impl-phases.md, rfc.md
  ├── [1m4ye] "Implement typed input extraction and deserialization (ASYA_PARAMS_AT_KEY)"  open
  ├── [1m589] "Implement JSON Schema generation and GET /schema endpoint"  open
  ├── [1mnzv] "Add unit and component tests for typed handler signatures"  open
  ├── [1m8sd] "Implement typed output merge and return serialization (ASYA_RESULT_AT_KEY)"  open
  ├── [1mbkh] "Update docs for typed handler signatures (ASYA_PARAMS_AT/ASYA_RESULT_AT)"  open
  └── [1m6hx] "Implement generator/yield typed serialization support"  open

[mxzgo] "Flow DSL Free Variables and Iteration"  P2 open  [0/2]
  .aint/active/aint.flow-dsl-free-variables-and-iteration.mxzgo/ rfc.md
  ├── [1fmjb] "DotGen: loop and async flow visualization"  open
  └── [1fel9] "Flow DSL: Support for loops (requires local variable serialization)"  open

[2w664] "A/B/N Traffic Routing for Actor Pipelines"  P2 open  [0/4]
  .aint/active/aint.abn-traffic-routing-for-actor-pipelines.2w664/ rfc.md
  ├── [1kmhe] "Observability: route-override hit rate metrics per actor"  open
  ├── [1kjq9] "Layer 2: Python router actor for weighted/probabilistic traffic splitting"  open
  ├── [1kvcm] "x-sump: surface route-override audit trail in error handling"  open
  └── [1kmt4] "Gateway: add Headers field to ActorMessage for API-driven route overrides"  open

[34xba] "Timeouts: per-actor and per-flow"  P2 open  [0/1]
  .aint/active/aint.timeouts-per-actor-and-per-flow.34xba/ impl-phases.md, rfc.md
  └── [zjt4h] "Implement cumulative retry time window (deadline_at SLA enforcement)"  open

[kchkv] "Agentic security"  P2 open  [0/4]
  .aint/active/aint.agentic-security.kchkv/ research-a2a-auth.md, research-mcp-auth.md, rfc.md
  ├── [1fdfm] "External secrets integration: Vault, ESO, cloud secret managers (post-v0)"  open
  ├── [iu978] "Phase 4: Enterprise auth (OAuth2 + OIDC for both protocols)"  open
  ├── [euanq] "XRD: validate secretName as DNS label (pattern constraint)"  open
  └── [1f63e] "Document TLS/mTLS deployment guidance"  open

[l899s] "New transports"  P2 open  [0/4]
  .aint/active/aint.new-transports.l899s/ claude.pubsub-vs-nats-vs-strimzi.txt
  ├── [1fgnn] "Add Redis Streams transport support (code + Crossplane)"  open
  ├── [1f07y] "Add NATS transport support (code + Crossplane)"  open
  ├── [1fula] "Research: Message queue size limits across transports"  open
  └── [1fifn] "Add Kafka transport support (code + Crossplane)"  open

[hb1v1] "Local testing workflow in docker-compose"  P2 open
  .aint/active/aint.local-testing-workflow-in-docker-compose.hb1v1/ notes-for-rfc.md

[1fw7s] "Implement AG-UI event streaming endpoint"  P2 open
  .aint/archive/aint.implement-ag-ui-event-streaming-endpoint.1fw7s.md

[1f7aw] "Implement input_required state for human-in-the-loop"  P2 open
  .aint/archive/aint.implement-input-required-state-human-loop.1f7aw.md

[1fkil] "Research: Adapt Gateway API to A2A/ACP/A2UI standards"  P3 open
  .aint/archive/aint.research-adapt-gateway-api-a2a-acp-a2ui-standards.1fkil.md

[1fgex] "Implement GET /tasks endpoint (list tasks)"  P3 open
  .aint/archive/aint.implement-get-tasks-endpoint-list-tasks.1fgex.md

[1foq3] "Add gRPC transport support"  P3 open
  .aint/archive/aint.add-grpc-transport-support.1foq3.md

[1f53y] "Implement push notification configuration endpoints"  P4 open
  .aint/archive/aint.implement-push-notification-configuration-endpoints.1f53y.md

[1fgyz] "Add A2UI payload support (optional)"  P4 open
  .aint/archive/aint.add-a2ui-payload-support-optional.1fgyz.md

Closed:
[1ftxe] Flow DSL: Support async/await, loops, and try-catch  merged
[1fj66] Transport: add SendWithDelay() and rename Nack() to Requeue()  merged
[8ctgi] Update existing flow examples and tests for new compiler pipeline  rejected
[tj91u] design+impl: replace nonRetryableErrors with errorRoutes in resiliency config  rejected
[1fze7] Phase 4.3: Update documentation for new architecture  merged
... and 360 more
