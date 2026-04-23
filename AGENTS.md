# AGENTS.md

AI developer guidance for the Asya project.

## Project Overview

Asya is an Actor Mesh framework for running AI workloads on Kubernetes using
choreography (decentralized) instead of centralized orchestration. Actors
communicate by passing envelopes through message queues; routing is embedded in
each envelope, not managed by a central coordinator. Implemented with **Crossplane Compositions**
for declarative actor deployment with inline sidecar rendering.

Core components (all in `src/`):
- **asya-sidecar** (Go): envelope router injected into actor pods; Queue → Sidecar → Runtime → Sidecar → Next Queue
- **asya-runtime** (Python): lightweight socket server loaded via ConfigMap; executes user handler,
  returns result. Source of truth: `src/asya-runtime/asya_runtime.py` (single file, no deps).
  `deploy/helm-charts/asya-crossplane/files/asya_runtime.py` is a symlink — editing the source
  automatically reflects in the Crossplane chart's ConfigMap. No manual sync needed.
- **asya-gateway** (Go): optional MCP/HTTP gateway; exposes async actor pipelines as synchronous HTTP
- **asya-crew** (Python): system actors — `x-sink` (persist results), `x-sump` (DLQ handling),
  `x-pause` (checkpoint envelope to S3 and signal `paused`), `x-resume` (restore envelope from S3
  and re-inject into the mesh)
- **asya-lab** (Python): CLI tools (`asya mcp ...`, `asya flow ...`) for debugging and flow compilation
- **asya-testing** (Python): shared test fixtures and utilities
- **asya-state-proxy** (Go): optional sidecar that gives actors virtual persistent state via filesystem
  emulation; actors read/write `/state/...` paths, runtime intercepts Python file I/O and forwards to the
  proxy over Unix socket; proxy translates to actual storage backend (S3, GCS, Redis, NATS KV) with
  configurable LWW or CAS guarantees; actors remain stateless Deployments — no StatefulSets

**Project structure**:

```
asya/
├── src/
│   ├── asya-gateway/
│   ├── asya-sidecar/
│   ├── asya-runtime/
│   ├── asya-crew/
│   ├── asya-testing/
│   └── asya-cli/
├── deploy/helm-charts/
│   ├── asya-crew/          # pre-built generic actors (like x-sink, x-sump)
│   ├── asya-crossplane/    # contains AsyncActor XRD
│   └── asya-gateway/       # sync stateful HTTP gateway exposing actors and flows as MCP tools or A2A agents
├── testing/
│   ├── component/          # docker-compose
│   ├── integration/        # docker-compose
│   ├── e2e/                # local kind cluster
│   └── shared/             # shared docker-compose configurations
└── examples/
│   ├── asyas/              # sample XR definitions
    └── flows/              # sample Python flows
```

See [docs/reference/components/](docs/reference/components/) for component deep-dives.

**Examples** (`examples/`):
- `asyas/` — real-world AsyncActor CRD manifests; use as reference when writing or reviewing actor specs
- `flows/` — teaser flow DSL files; comprehensive examples (including agentic flows) are in [examples/end-to-end/monorepo/](examples/end-to-end/monorepo/)
- `end-to-end/monorepo/` — full working examples organized by category (control-flow, agentic, resiliency, compiler-sugar, text-improver)

**Crossplane chart** (`deploy/helm-charts/asya-crossplane/`): Deploys XRDs, Compositions, and provider configurations for AsyncActor resource management. The `render-deployment` composition step renders the complete pod spec (runtime container + asya-sidecar + state proxies + volumes) using values from the chart's `sidecar:` block.

## Quick Reference

**Prerequisites**: uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`), Go 1.24+, Python 3.13+, Docker, Make

```bash
make setup              # Install uv, pre-commit hooks, sync Go deps
make build              # Build all components
make build-images       # Build Docker images
make build-go           # Build Go components only
make test-unit          # Unit tests (Go + Python)
make test-component     # Component tests (Docker Compose)
make test-integration   # Integration tests (Docker Compose)
make test-e2e           # E2E tests (Kind cluster)
make lint               # Run all linters with auto-fix
make clean              # Remove build artifacts
```

Prefer `make <target>`. Add new Makefile targets instead of repeating raw commands.

## Testing Strategy
**Hierarchy**:
1. **Unit** (`make test-unit`): fast, no external deps — `src/{component}/tests/`
2. **Component** (`make test-component`): single component in Docker Compose — `testing/component/{component}/`
3. **Integration** (`make test-integration`): multi-component Docker Compose — `testing/integration/{suite}/`
4. **E2E** (`make test-e2e`): full stack in Kind cluster — `testing/e2e/`

**Trust CI**: Component, integration, and e2e tests cannot be parallelized across PRs. For multi-PR work,
push and observe CI logs rather than running all suites locally.

**Critical rules**:
- Unit tests must mock all external services
- Component/integration tests run inside Docker Compose — no port-forwarding
- Only E2E tests may use `kubectl port-forward`
- Prefer Docker Compose over Kind; use Kind only for K8s-specific features (CRDs, KEDA, Crossplane)

**E2E local debugging** (only when user explicitly permits Kind cluster access):

Kind cluster recreation costs 15-25 minutes. Never `make down && make up` to fix a flaky test.
Use the fast-path instead:

```bash
make build-images
kind load docker-image {image}:{tag} --name asya-e2e-{profile}
helm upgrade -n {namespace} {release} deploy/helm-charts/{chart}/ --reuse-values
kubectl rollout restart -n {namespace} deployment/{name}
```

Run with fail-fast: `make trigger-tests PYTEST_OPTS="-vv -x" PROFILE="sqs-s3" 2>&1 | tee /tmp/tests.txt`

**Lessons from field debugging**:
1. **Assert intent, not syntax** — composition tests that match exact variable names (e.g. `$xr.spec.actor`)
   break on refactors; assert the behavioral intent instead
2. **XRD field removals cascade** — when removing a field from an XRD, immediately grep for it in test code
   and helpers
3. **Helm test pod namespacing** — test pods inherit `Release.Namespace`; secrets may live in a different
   namespace (e.g. `asya-system`); verify before referencing; `deploy.sh` is canonical for what exists in
   the actor namespace at test time
4. **Chaos tests need sequential workers** — pod-kill tests interfere with parallel pytest workers; use
   `-p no:xdist` when debugging
5. **CI-only failures are usually namespace/credential issues** — local dev often papers over these because
   secrets are created ad-hoc; CI is strict about what exists where
6. **AsyncActor manifest field additions cascade across test files** — when a new required field is added to
   AsyncActor specs (e.g. `compositionSelector`), grep ALL test files for `kind: AsyncActor` or `transport:`
   to find every inline manifest; missing even one causes failures in seemingly unrelated suites
   (e.g. fixing `test_crossplane_e2e.py` but missing `test_secret_injection_e2e.py`)

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed test structure, Makefile patterns, and Docker Compose
profile assembly.

## Envelope Protocol

```json
{
  "id": "<envelope-id>",
  "parent_id": "<original-id>",
  "route": {"prev": [], "curr": "q1", "next": ["q2"]},
  "headers": {"trace_id": "..."},
  "payload": {}
}
```

- **Runtime** (not sidecar) shifts the route: `prev` grows, `curr` advances, `next` shrinks
- `x-sink` and `x-sump` are **automatic** — never include them in route configs
  - Empty `route.curr` or `None` return → sidecar routes to `x-sink`
  - Runtime error → sidecar applies resiliency policy (retry or route to `x-sink` with phase: failed)
- Modify routing from a generator handler: `yield "SET", ".route.next", ["actor_a"]`
- Only `.route.next`, `.headers`, and `.status` are writable; `.route.prev`, `.route.curr`, `.id`, `.parent_id` are read-only

See [docs/reference/specs/envelope.md](docs/reference/specs/envelope.md).

## Agentic Capabilities

Asya's strategic goal is to provide the full agentic tool surface that frameworks like Google ADK,
Mastra, and LangGraph provide — but on a stateless, queue-based, K8s-native mesh. Agentic flow
patterns live in [examples/end-to-end/monorepo/src/agentic/](examples/end-to-end/monorepo/src/agentic/).
See the framework survey in `.aint/aints/agentic-umbrella/survey-agentic-frameworks.md`.

### Actor vs Flow

Both actors and flows share a `dict -> dict` signature, but they are fundamentally different:

- **Actor**: a deployed CRD (`AsyncActor`), runs as a pod with a sidecar, can yield FLY events,
  abort, fan-out (multiple yields), or return `None`
- **Flow**: ephemeral — no CRD, no pod, just a Python file that describes a pipeline as familiar
  Python control flow (`if/else`, sequential calls). The Flow DSL compiler transforms it into a
  group of router actors using **CPS (continuation-passing style)**: instead of calling the next
  function, each step sends a message to the next actor's queue.

Flows support fan-out/fan-in via list comprehensions, list literals, and `asyncio.gather`.
Individual actor calls within flows must map payload **1:1**:
- ✅ `return payload` (function actor)
- ✅ exactly one `yield payload` (generator actor, no FLY yields)
- ✅ `[actor(x) for x in items]` — fan-out with automatic fan-in aggregation
- ✅ `asyncio.gather(a(x), b(y))` — heterogeneous fan-out with aggregation
- ❌ `yield "FLY", ...` — not supported in flows (FLY is actor-only)
- ❌ fire-and-forget fan-out (multiple `yield` without aggregation) — actor-only
- ❌ returning `None` (abort) — not supported in flows

### ABI Yield Protocol

Generator handlers communicate with the runtime via structured yields. Full spec:
`docs/reference/specs/abi-protocol.md`.

| Yield form | Effect |
|---|---|
| `yield payload` | Emit envelope downstream (to next actor in route) |
| `yield "GET", ".route.prev"` | Read envelope metadata |
| `yield "SET", ".route.next", [...]` | Overwrite routing |
| `yield "FLY", {...}` | Stream event upstream to gateway (ephemeral SSE, not persisted) |

**FLY vs history**: FLY events reach only connected SSE clients — use for streaming tokens and live
progress. For data that must survive pause/resume or be readable by downstream actors, append to
`payload.a2a.task.history[]` instead.

### Pause / Resume (Human-in-the-Loop)

An actor signals a pause by routing to `x-pause` (via `yield "SET", ".route.next", ["x-pause"]`).
The `x-pause` crew actor checkpoints the full envelope (payload + route + headers) to S3 and reports
`paused` status to the gateway. The gateway maps `paused` → A2A `input_required`.

On resume, the client POSTs new input to the gateway, which routes to `x-resume`. The `x-resume`
actor fetches the checkpointed envelope from S3, merges the new input into the payload, and
re-dispatches to the mesh — continuing from where the pipeline stopped.

### Gateway Routes (asya-gateway)

Three fixed namespaces (planned `ASYA_BASE_PREFIX`, not yet implemented, would be prepended to all):

| Namespace | Audience | Purpose |
|---|---|---|
| `/a2a/` | External AI agents, orchestrators | Full A2A protocol (SendMessage, GetTask, Subscribe, pause/resume, push notifications) |
| `/mcp/` | LLM clients, developers | MCP Streamable HTTP + legacy SSE, REST tool invocation |
| `/mesh/` | Sidecars, operators | Progress/FLY/final reporting from sidecars; `POST /mesh/config-reload` for immediate ConfigMap reload |
| `/stream/` | Any client (A2A, MCP, UI) | Ephemeral FLY SSE — live per-token streaming by task ID |

Special root routes (unaffected by base prefix):
- `/.well-known/agent.json` — A2A Agent Card discovery
- `/health` — K8s liveness/readiness probe

A2A task state mapping: `pending` → `submitted`, `running` → `working`, `succeeded` → `completed`,
`paused` → `input_required`, `failed` → `failed`, `canceled` → `canceled`, `auth_required` → `auth_required`.

## AI Automation Policies

### Worktree Isolation

**All feature work must be done in a git worktree.** Never implement features directly on `main`.

1. `git aint pickup <ref>` — creates worktree in `.worktrees/<epic>/<task>.<slug>` and feature branch
2. Work exclusively in the worktree
3. Commit, push, create a PR — never merge directly

### DCO Sign-off (REQUIRED)

All commits **must** include a `Signed-off-by:` trailer (DCO — Developer
Certificate of Origin). CI will reject PRs with unsigned commits.

- **Every commit**: use `git commit --signoff` (or `-s`)
- **After rebase**: `git rebase --exec 'git commit --amend --no-edit --signoff'`
- **Verify before push**: `git log --format='%h %s | SOB:%(trailers:key=Signed-off-by,valueonly)'`
- **Never use** `--no-verify` to bypass pre-commit hooks

### Command Hierarchy

1. **Prefer**: `make <target>`
2. **Last resort**: direct commands only if no Makefile target exists

Add new Makefile targets instead of repeating raw commands.

### Cheap Subagents for Mechanical Fixes

Use Haiku/Sonnet subagents for lint errors and unit test failures — these are mechanical fixes.

**Pattern**: Run `make lint` or `make test-unit` → capture errors → spawn `Task` subagent with
`model: "haiku"` → pass errors and file paths → verify with re-run.

**Haiku handles**: formatting (ruff, gofmt, yamlfmt), import ordering, simple assertion fixes.
**Keep on Opus**: root cause analysis, architectural decisions, complex refactoring.

### Documentation Policy

Never proactively create documentation files (*.md, README.md, design docs) unless explicitly
requested. Updating existing docs to reflect code changes is fine.

- `docs/` contains only documentation content (.md files). Website assets live in `docs/website/`.
- Mirrored guides in `usage/` and `setup/` must cross-link each other.
- `docs/plans/` is gitignored and must never be committed. Use aint for work tracking.

### Documentation Discovery

Every file in `docs/` has a YAML frontmatter `description` field — a grep-friendly one-liner with
searchable keywords. Use this to find the right doc fast:

```bash
# Search for a topic across all doc descriptions (fastest)
grep -r "description:.*routing" docs/ --include="*.md" -l

# Browse all descriptions at a glance
grep -rn "^description:" docs/ --include="*.md"

# Find docs about a specific component
grep -r "description:.*sidecar" docs/ --include="*.md" -l

# Find docs about a concept or pattern
grep -rE "description:.*(fan-out|fan-in|streaming)" docs/ --include="*.md" -l
```

**Doc sections** (`docs/`):

| Section | Audience | Content |
|---------|----------|---------|
| `concepts/` | Everyone | What Asya is, architectural ideas, design principles |
| `setup/` | Platform engineers | Deployment, Helm config, autoscaling, observability |
| `usage/` | Data scientists | Tutorials, handler patterns, agentic patterns, debugging |
| `reference/` | Both | Component specs, API specs, env vars, transport/storage config |
| `comparisons/` | Evaluators | Asya vs other frameworks (Temporal, LangGraph, Ray, etc.) |
| `contributing/` | Contributors | Test strategies, cross-component architecture decisions |

**Naming conventions**: `start-*` = getting started tutorials, `guide-*` = how-to guides,
`ops-*` = operations/debugging, `core-*` = core components, `lab-*` = developer tools,
`as-*` = category comparisons, `vs-*` = 1:1 deep comparisons.

When you need documentation context, grep descriptions first — don't read files speculatively.

### Code Comment Policy

Never use transitional comments ("instead of", "increased from", "no need to"). Comments explain
what/why the current code does — not how it differs from before.

### Environment Variable Defaults

Never add defaults to env vars in code or docker-compose files. All required env vars must be passed
explicitly from Makefile. Fail fast on missing config.

```yaml
- ${COVERAGE_DIR}:/app/.coverage:rw              # good
- ${COVERAGE_DIR:-.coverage}:/app/.coverage:rw   # bad — hides missing config
```

### Sleep Policy

Never use `time.Sleep`/`time.sleep` in production code. In tests, polling sleeps are allowed but must
have an inline comment explaining purpose.

### Emoji Policy

**In .md files**: only ✅ ❌ ⚠️ 🟢 🟡 🔴 allowed.
**In code files** (.py, .go, .sh, .yaml): no emojis. Use `[+]` / `[-]` / `[!]` / `[.]` text markers.

## Landing the Plane (Session Completion)

Work is **not complete** until `git push` succeeds. Do not stop before pushing.

1. File issues for remaining work
2. Run quality gates (if code changed): tests, lint, build
3. Update issue status (close finished, update in-progress)
4. Push:
   ```bash
   git pull --rebase
   git aint sync
   git push
   git status  # must show "up to date with origin"
   ```
5. Clean up stashes, prune remote branches
6. Provide context for next session

Never say "ready to push when you are" — you must push.

## git-aint

This project uses [git-aint](https://github.com/atemate/git-aint) for issue tracking. Run
`git aint init` to initialize (idempotent). `.aint/` is a git worktree on branch `aint-sync`,
shared across all agents. See [.aint/AGENTS.md](.aint/AGENTS.md) for full usage.


## Coding Guidelines for Agents

@AGENTS_GUIDELINES.md
