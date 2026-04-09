# Enterprise Coding Agent Platform

## The Problem

Today, agentic coding tools (Claude Code, Goose, Aider, Cursor agent mode,
Windsurf) run **on the developer's local machine**. This means:

- Tests, builds, and deployments execute locally — limited by laptop resources
- Each developer maintains their own environment (Python versions, Go toolchains,
  Docker, kind clusters)
- No isolation between projects — a runaway test can eat all RAM
- No centralized observability — the DevX team can't see what agents are doing
- No cost control — each developer burns their own API keys
- No guardrails — agents can run arbitrary commands on local machines
- No reuse — when developer A solves a build problem, developer B hits it again

## The Vision

A company's Developer Experience (DevX) team provides **Coding Agent as a
Service**: a centralized, scalable, isolated execution environment where agentic
coding tools run on Kubernetes via Asya.

Developers connect from their IDE (VS Code, JetBrains, terminal) via MCP. The
agent runs in an isolated container with the right toolchain, project-specific
secrets, and full Kubernetes resources. Heavy operations (test suites, builds,
multi-repo analysis) dispatch to the Asya mesh for parallel, auto-scaled
execution.

## Why Asya (Not Just "Containers on K8s")

Plain Kubernetes (Deployments + Services) gives you containers but not:

1. **Interactive protocol**: Asya gateway speaks MCP and A2A natively. Developers
   connect from any MCP-compatible client — no custom WebSocket server needed.
2. **Queue-based dispatch**: Heavy operations (test suites across 20 repos) fan
   out to the mesh. Each test runner scales independently via KEDA.
3. **Pause/resume**: Long pipelines (multi-hour refactoring) checkpoint to S3.
   Developer closes laptop, comes back tomorrow, resumes from exact point.
4. **Streaming**: FLY events stream agent progress to the IDE in real-time — each
   file edit, each test result, each reasoning step.
5. **Guardrails as infrastructure**: Safety sandwich (input validation → agent →
   output filter) is compiled into the actor graph, not bolted on as middleware.
6. **Audit trail**: Every envelope carries the full processing history. Compliance
   can inspect any agent action.
7. **Durable execution**: If a node dies mid-test-suite, the queue retries. No
   lost work.

## Architecture

```
Developer's IDE                     Company K8s Cluster
+-----------------+                +------------------------------------------+
| VS Code / Term  |  MCP over     | agentgateway (Rust, LF)                  |
|                 |  HTTPS        |   - MCP federation                       |
| MCP client      |<------------>|   - OIDC auth (Keycloak/Auth0)           |
| (Claude Code,   |               |   - Per-tool RBAC (CEL expressions)      |
|  Goose, etc.)   |               |   - Rate limiting, guardrails            |
+-----------------+               |   - Admin UI / MCP playground            |
                                  +------------------+------------------------+
                                                     |
                                  +------------------v------------------------+
                                  | asya-bridge (Go, stateless, ~1,500 LOC)   |
                                  |   - Create envelopes, publish to queues   |
                                  |   - Subscribe to status/FLY subjects      |
                                  |   - Stream results back via SSE           |
                                  +------------------+------------------------+
                                                     |
                                  +------------------v------------------------+
                                  | Transport (NATS JetStream)                |
                                  |   - actor input queues (work distribution)|
                                  |   - status.{task_id} (retained)           |
                                  |   - fly.{task_id} (ephemeral streaming)   |
                                  +--+--------+--------+---------------------+
                                     |        |        |
                              +------v--+ +---v----+ +-v---------+
                              | Coding  | | Test   | | Build     |
                              | Agent   | | Runner | | Runner    |
                              | Actor   | | Actors | | Actors    |
                              | (1/user)| | (KEDA) | | (KEDA)   |
                              +---------+ +--------+ +-----------+
                                  |
                              +---v-----------+
                              | Workspace     |
                              | (PVC or       |
                              |  emptyDir +   |
                              |  git clone)   |
                              +---------------+
```

## The Hybrid Actor Model

The coding agent is NOT a pipeline of actors (too slow for interactive use).
It's a **single long-lived actor** that:

1. **Runs the tight inner loop locally** — file reads, writes, git operations,
   small shell commands execute inside the actor pod in sub-second time. No queue
   hops. This is the ReAct cycle: LLM → tool → observe → repeat.

2. **Dispatches heavy operations to the mesh** — test suites, builds, linting
   across repos, security scans fan out to specialized actors via the normal Asya
   envelope routing. These actors scale independently via KEDA.

3. **Streams everything via FLY** — every file edit, command output, reasoning
   step streamed to the developer's IDE in real-time.

4. **Pauses for human approval** — dangerous operations (force push, production
   deploy, delete database) route to `x-pause`. Developer reviews in IDE and
   approves or rejects.

```
                Coding Agent Actor (single pod per session)
                +------------------------------------------+
                |                                          |
                |  ReAct Loop (in-process, fast):           |
                |    LLM call (Claude API)                 |
                |      → file read/write (local fs)        |
                |      → git operations (local binary)     |
                |      → small shell cmds (subprocess)     |
                |      → yield FLY (stream to IDE)         |
                |      → repeat                            |
                |                                          |
                |  Heavy dispatch (via mesh, parallel):     |
                |    yield envelope → test-runner actors    |
                |    yield envelope → build-runner actors   |
                |    yield envelope → scan-runner actors    |
                |    (fan-out/fan-in with KEDA scaling)     |
                |                                          |
                |  Human gates:                             |
                |    yield SET ".route.next" ["x-pause"]   |
                |    (checkpoint → IDE shows approval UI)   |
                +------------------------------------------+
```

## Developer Experience

### Connecting

```bash
# Developer authenticates once (OIDC via company SSO)
asya auth login

# IDE auto-discovers tools via MCP
# agentgateway returns: coding-session, run-tests, deploy, scan-security, ...
```

### Session Lifecycle

```
1. Developer sends message from IDE
2. agentgateway authenticates (OIDC token), enforces RBAC
3. asya-bridge creates envelope, publishes to coding-agent queue
4. KEDA scales up coding-agent pod (if not running)
5. Pod starts with:
   - Project container image (Python 3.13 + Node 20 + project deps)
   - Workspace volume (PVC with git checkout, or emptyDir + clone)
   - Secrets (GitHub token, API keys from namespace Secret)
6. Agent executes task, streams FLY events
7. Developer sees real-time progress in IDE
8. Agent completes → result returned via MCP
9. Pod stays warm for follow-up messages (cooldown: 5 min)
10. After inactivity → KEDA scales to zero
```

### Multi-Turn Conversations

```
Turn 1: "Fix the authentication bug in login.py"
  → Agent reads files, identifies bug, proposes fix, streams reasoning
  → Writes fix, runs related unit tests
  → Returns: "Fixed null check on line 42, tests pass"

Turn 2: "Now add integration tests for the fix"
  → Same context_id, same workspace, conversation history preserved
  → Agent reads existing test patterns, writes new tests
  → Dispatches full test suite to test-runner actors (fan-out)
  → Returns: "Added 3 integration tests, all 47 tests pass"

Turn 3: "Create a PR"
  → Agent runs git commit, git push
  → Calls GitHub API (via namespace secret)
  → Returns: "PR #142 created: Fix auth null check"
```

## Enterprise DevX Platform Features

### For the Platform Team

- **Project templates**: Pre-built container images per tech stack
  (Python, Node, Go, Java) with standard toolchains
- **Secret management**: Per-project Kubernetes Secrets with GitHub tokens,
  API keys, cloud credentials — injected via `secretRefs`
- **Cost attribution**: Per-user, per-project compute + LLM token tracking
  via sidecar metrics with `client_id` labels
- **Guardrails**: agentgateway's CEL-based RBAC + content guardrails prevent
  agents from accessing unauthorized repos or running dangerous commands
- **Audit trail**: Every agent action is in the envelope. Compliance team
  can inspect any session.
- **Capacity planning**: KEDA metrics show concurrent sessions, queue depths,
  pod utilization across all projects

### For Developers

- **Zero setup**: Connect from IDE, start coding. No local environment to maintain.
- **Full isolation**: Each session runs in its own pod. Your runaway test doesn't
  affect anyone else.
- **Persistent workspace**: Git checkout persists across sessions (PVC or
  state-proxy). Come back tomorrow and continue.
- **Shared tooling**: Platform team maintains linters, formatters, test frameworks.
  Every project gets the same standard toolchain.
- **Fast heavy ops**: Test suites fan out across the mesh. 20 test files run on
  20 pods in parallel. What takes 10 minutes locally takes 1 minute on the mesh.

### For Engineering Leadership

- **Visibility**: Dashboard showing agent adoption, session durations, success
  rates, cost per team
- **Standardization**: Every team uses the same coding agent configuration.
  Best practices enforced at platform level.
- **Scalability**: Add more nodes to the cluster, not more developer laptops.
  100 concurrent coding sessions is a scaling problem, not a procurement problem.
