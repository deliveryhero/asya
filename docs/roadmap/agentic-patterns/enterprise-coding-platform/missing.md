# Enterprise Coding Platform: Missing Functionality

This is the largest gap analysis because the use-case is furthest from Asya's
current sweet spot (stateless pipelines). Organized by architectural layer.

---

## Layer 1: Gateway / Protocol (agentgateway + asya-bridge)

### P0-GW-1. MCP blocking tools/call

**Current state**: MCP `tools/call` dispatches to queue and returns immediately.
Coding MCP clients (Claude Code, Goose) expect synchronous tool results —
they call a tool and wait for the answer inline.

**Files** (current gateway, pre-rearchitect):
- `src/asya-gateway/internal/mcp/handlers.go:84-139` — returns task metadata

**What's needed**:
- asya-bridge: hold HTTP connection, subscribe to `status.{task_id}`, relay
  FLY events inline, return final result when terminal status arrives
- Timeout: per-tool configurable, default to tool's `timeout_sec`
- This is the #1 blocker. Without it, no MCP client can use Asya as backend.

**In rearchitected world**: asya-bridge subscribes to NATS `status.{id}`
subject — blocking wait is a simple `sub.NextMsg(timeout)` loop. Much
simpler than current PG poll + channel approach.

### P0-GW-2. MCP session/conversation continuity

**Current state**: Each MCP `tools/call` creates a new task. No way to
maintain conversation context across calls. Developer's multi-turn
conversation ("fix the bug" → "add tests" → "create PR") creates 3
independent tasks with no shared state.

**What's needed**:
- Session ID parameter on MCP tools/call (or derived from MCP session)
- Session maps to a specific coding-agent pod (sticky routing)
- Pod keeps workspace and conversation state in memory across calls
- asya-bridge routes by session ID to the right actor queue

**Design options**:
- (a) agentgateway's MCP session → session header on bridge requests
- (b) NATS subject per session: `coding.{session_id}` → specific pod subscribes
- (c) Sticky queue consumer: pod subscribes with consumer group = session ID

### P0-GW-3. Per-tool RBAC and project isolation

**Current state**: All authenticated clients can call all tools. No way to
restrict developer A to project-A tools only.

**In rearchitected world**: agentgateway provides **CEL-based per-tool RBAC**
out of the box. The DevX team writes rules like:
```yaml
rules:
  - match: "tool.name.startsWith('project-a/')"
    allow: "user.groups.contains('team-a')"
```
This is FREE with agentgateway — no Asya code needed.

---

## Layer 2: Actor / Runtime

### P0-RT-1. Subprocess execution in actor handler

**Current state**: Python runtime executes handler functions via
`asyncio.run()` or direct call. No support for subprocess, Popen, or shell
command execution. Coding agents MUST execute shell commands (git, make,
npm, pytest, etc.).

**Files**:
- `src/asya-runtime/asya_runtime.py:593-636` — handler execution, no subprocess

**What's needed** (two options):

**(a) Allow subprocess in Python handlers** (simpler):
- No runtime change needed — Python handlers CAN call `subprocess.run()`.
  The runtime doesn't prevent it. The limitation is that the handler must
  be Python, and subprocess results must be returned in the payload dict.
- This actually works today. The "gap" is more about handler design patterns
  and container image setup (install git, make, etc.) than runtime changes.
- Document the pattern and provide a reference handler.

**(b) Non-Python actor runtime** (more flexible):
- Alternative runtime protocol: sidecar talks to any process via stdin/stdout
  or HTTP, not just the Python socket server.
- Actor container runs Claude Code binary (or any agent binary) directly.
- Sidecar sends envelope via HTTP, receives response + FLY events.
- Requires: new runtime adapter in sidecar (not just Python socket protocol).

**Recommendation**: Start with (a). Python handler that wraps subprocess calls
is sufficient. The handler IS the coding agent — it calls the LLM, reads
files, runs commands, all within a single handler invocation.

### P0-RT-2. Long-running handler execution

**Current state**: `resiliency.actorTimeout` enforces a per-message timeout.
A coding session can last hours — a single "fix this bug" task might involve
20 LLM calls, 50 file reads, 10 test runs.

**Files**:
- `deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml:275-277`
  — actorTimeout field
- `src/asya-sidecar/internal/router/` — timeout enforcement

**What's needed**:
- Very long timeout for coding-agent actors: `actorTimeout: "4h"` or similar
- Or: no timeout (infinite), relying on external session management to kill
  idle pods via KEDA scale-down
- Timeout budget preserved across pause/resume (already works)

**Risk**: Long-running handlers tie up a queue consumer slot. If the actor
has `maxReplicaCount: 1`, only one session runs at a time.
**Mitigation**: Each user gets their own actor/queue (see session routing below).

### P1-RT-3. Per-session actor routing (sticky sessions)

**Current state**: Actors consume from a shared queue. All messages to the
`coding-agent` queue go to any available pod. A developer's second message
might hit a different pod (different workspace, different state).

**What's needed**:
- Per-session queue or routing key: `coding.{user_id}.{session_id}`
- Each session pod subscribes only to its session's messages
- KEDA ScaledObject per session (or per user)
- Session creation: first message creates queue + triggers pod scale-up
- Session teardown: inactivity → KEDA scales to zero → queue deleted

**Design options**:
- (a) Dynamic AsyncActor CRD per session (Crossplane creates queue + pod)
- (b) NATS consumer groups with session ID as durable name
- (c) Single actor with internal routing (actor pod dispatches by session)

**Recommendation**: (b) with NATS JetStream. Each session pod is a durable
consumer on `coding.{session_id}`. No CRD churn. KEDA scales based on
consumer pending count.

---

## Layer 3: Workspace & State

### P0-WS-1. Workspace volume strategy

**Current state**: No built-in workspace management. Actors get an emptyDir
or state-proxy mount. No PVC support in the default composition.

**What's needed** (tiered approach):

**(a) Ephemeral workspace** (simplest, good for short sessions):
- emptyDir volume + `git clone` on pod start (init container)
- Workspace lost on pod termination
- Fine for: one-shot tasks ("fix this file", "run tests")

**(b) PVC-backed workspace** (persistent across sessions):
- ReadWriteOnce PVC per session, mounted at `/workspace`
- Survives pod restarts and scale-to-zero events
- Requires: PVC lifecycle management (create on session start, delete after
  inactivity, or retain for N days)
- Requires: composition template change to support PVC volumes

**(c) Git-based persistence** (stateless pods):
- emptyDir + git clone at start + git push at end
- No PVC needed — workspace state is in git
- Works for code changes but not for build artifacts (node_modules, venv)
- Fastest cold start if git repo is small

**Recommendation**: Start with (c) for code, add (b) for projects that need
build artifact persistence. State-proxy S3 can supplement for large artifacts.

### P1-WS-2. Container image per project/tech stack

**Current state**: Actors use a single container image specified in the
AsyncActor CRD. No built-in concept of "project template" images.

**What's needed**:
- Project template registry: `coding-agent-python:3.13`, `coding-agent-node:20`,
  `coding-agent-go:1.24`, `coding-agent-java:21`
- Each template includes: base toolchain + git + standard tools + asya runtime
- Dynamic image selection: agentgateway routes based on project metadata
  → asya-bridge selects appropriate actor template
- Or: per-project AsyncActor CRD with the right image (platform team maintains)

### P1-WS-3. Build artifact caching across sessions

**What's needed**:
- Shared read-only mounts for common dependencies (npm cache, pip cache,
  Go module proxy)
- State-proxy S3 mount for per-project build caches
- Container image layers with pre-installed project dependencies (built by CI)

---

## Layer 4: Mesh Dispatch (Heavy Operations)

### P1-MD-1. Fan-out from within a handler (not flow DSL)

**Current state**: Fan-out is a Flow DSL construct compiled into router actors.
A coding agent handler running the ReAct loop can't fan-out mid-execution
to parallelize test runs.

**What's needed**:
- ABI extension: `yield "DISPATCH", {"actor": "test-runner", "payload": {...}}`
- Sidecar creates child envelope, publishes to target actor's queue
- Handler continues (doesn't wait — fire-and-forget for parallel ops)
- Or: `results = yield "DISPATCH_WAIT", [{"actor": "test-runner", ...}, ...]`
  for synchronous fan-out within the handler

**Alternative**: Handler publishes directly to NATS (bypassing sidecar). Less
elegant but works today with the right client library in the container.

### P1-MD-2. Shared test/build runner actors

**What's needed** (crew actor library for coding):
- `x-test-runner`: Runs test commands in isolated container, streams output
  via FLY, returns pass/fail + coverage
- `x-build-runner`: Runs build commands, streams output, returns artifacts
- `x-lint-runner`: Runs linters, returns findings
- `x-scan-runner`: Security scanning (SAST, dependency audit)

These actors are pre-deployed by the platform team. Coding agents dispatch
to them for heavy operations. Each scales independently via KEDA.

---

## Layer 5: Enterprise Platform

### P1-EP-1. Cost attribution and quotas

**What's needed**:
- Sidecar metrics with `client_id` label (from envelope header)
- LLM token tracking: handler reports usage to sidecar via ABI
  `yield "SET", ".headers.x-asya-usage", {"tokens": 5000, "model": "claude-4"}`
- Compute time tracking: sidecar records wall-clock per handler invocation
- Aggregation: usage table or NATS KV keyed by `{client_id, date}`
- Quota enforcement: agentgateway rate limiter checks remaining budget

### P1-EP-2. Session management dashboard

**What's needed**:
- List active sessions: which users, which projects, how long running
- Session metrics: LLM calls, tool invocations, files modified, tests run
- Kill session: terminate runaway coding agent
- agentgateway admin UI could be extended for this

### P2-EP-3. Shared knowledge across sessions

**What's needed**:
- When developer A solves a build issue, the solution is captured
- Next time developer B hits the same issue, the agent recalls the fix
- Implementation: state-proxy S3 mount with team-scoped knowledge base
- Or: external memory system (vector DB) accessible from agent handlers

### P2-EP-4. Pre-built action templates

**What's needed**:
- Common coding tasks as pre-compiled flows:
  - "Fix failing CI" (fetch CI logs → analyze → fix → push → verify)
  - "Refactor function" (analyze → plan → edit → test → PR)
  - "Add feature from spec" (read spec → plan → implement → test → PR)
- These are MCP tools in agentgateway's tool registry
- Reusable across all projects

---

## Priority Summary

| ID | Gap | Layer | Priority | Effort |
|---|---|---|---|---|
| GW-1 | MCP blocking tools/call | Gateway | P0 | 1-2 weeks |
| GW-2 | Session/conversation continuity | Gateway | P0 | 2-3 weeks |
| RT-1 | Subprocess execution pattern | Runtime | P0 | 1 week (docs + ref handler) |
| RT-2 | Long-running handler execution | Runtime | P0 | 1 week (config) |
| WS-1 | Workspace volume strategy | Workspace | P0 | 2-3 weeks |
| GW-3 | Per-tool RBAC | Gateway | P0 | 0 (free with agentgateway) |
| RT-3 | Per-session actor routing | Runtime | P1 | 3-4 weeks |
| WS-2 | Container image per stack | Workspace | P1 | 2-3 weeks |
| MD-1 | In-handler fan-out dispatch | Mesh | P1 | 2-3 weeks |
| MD-2 | Shared runner crew actors | Mesh | P1 | 3-4 weeks |
| EP-1 | Cost attribution | Platform | P1 | 3-4 weeks |
| WS-3 | Build artifact caching | Workspace | P1 | 2 weeks |
| EP-2 | Session dashboard | Platform | P1 | 2-3 weeks |
| EP-3 | Shared team knowledge | Platform | P2 | 4-6 weeks |
| EP-4 | Pre-built action templates | Platform | P2 | ongoing |

## What agentgateway Gives for Free

The gateway rearchitecture (aint `gateway-rearchitect/2zia`) is a major
accelerator for this use-case:

- **MCP federation**: Aggregate coding agent tools + external MCP servers
  (GitHub MCP, Jira MCP, Slack MCP) into a single endpoint
- **Per-tool RBAC**: CEL expressions restrict access by user/team/project
- **Rate limiting**: Token bucket per user prevents runaway sessions
- **Content guardrails**: Prevent agents from outputting secrets, PII
- **OIDC auth**: Plug into company SSO (Keycloak, Auth0, Okta)
- **Admin UI**: View active tools, sessions, metrics
- **OTLP observability**: Trace every tool call through Jaeger/Langfuse

These would require months of engineering on the current gateway. With
agentgateway, they're configuration.
