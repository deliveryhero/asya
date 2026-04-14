---
title: "Phase 5: Docker Compose CLI + socket transport"
status: working
priority: 2
assignee: Artem Yushkovskiy
dependencies:
  - 5ifn
  - cavw
tags:
  - worktree:.worktrees/.worktrees/asya-lab/i6o8.phase-5-docker-compose-cli-socket-transport
  - branch:asya-lab/i6o8.phase-5-docker-compose-cli-socket-transport
  - pr:305
---

## Scope

Docker Compose commands for local testing, plus compose file generation.

### 5a. asya d up <target>

1. Auto-compile if given `.py` file
2. Generate `docker-compose.yaml` from compiled manifests
3. Each actor gets: sidecar container + runtime container (same architecture as K8s)
4. Socket transport (`ASYA_TRANSPORT=socket`) for inter-actor communication - implemented in PR 299
5. Shared Docker volume at `/var/run/asya/mesh/` for Unix sockets
6. `docker compose up -d`

### 5b. asya d down <target>

- `docker compose down` for the flow's compose project

### 5c. asya d send <target> '{}'

- Write envelope to actor's Unix socket

### 5d. asya d logs <target>

- `docker compose logs -f`

### Two testing tiers

| Tier | What runs | Transport |
|------|-----------|-----------|
| Single actor | `asya d up <actor.py>` (`@actor` handler) | HTTP (runtime as server) |
| Full flow | `asya d up <flow.py>` | Socket (sidecar + runtime per actor) |

### Secrets handling

When `asya d up` detects env vars mapped to K8s secrets, it checks `.env.secret`.
Missing = error with hint to `asya k secret show -o env >> .env.secret`.

### Socket transport prerequisite

[cavw] implements the Go socket transport in the sidecar
(`src/asya-sidecar/internal/transport/socket/`). Each actor's sidecar listens
on `/var/run/asya/mesh/<actor-name>.sock`. A shared Docker volume makes all
sockets visible to all sidecars.

Constraints (acceptable for local testing):
- Single replica per actor
- No queue-level DLQ
- No KEDA autoscaling
- Sequential FIFO delivery

## Dependencies

- [5ifn] Phase 3: Local CLI (compile command)
- [cavw] Socket transport implementation in sidecar (Go)

## State proxy in Docker Compose

State proxy mounts are emulated via regular Docker volumes. The runtime env var
`ASYA_STATE_PROXY_MOUNTS` is intentionally NOT set — when unset, `asya_runtime.py`
does not intercept file I/O, so mount paths resolve to real directories on disk.
No state proxy sidecar containers are needed. If an actor's manifest references
state mounts, the compose generator creates Docker volumes for those paths.

## Execution Plan

### Step 1: `compose.py` — Docker Compose YAML generator

Parse multi-doc AsyncActor YAML manifests and generate `docker-compose.yaml`:
- For each actor: sidecar service + runtime service
- Sidecar env: `ASYA_TRANSPORT=socket`, `ASYA_ACTOR_NAME=<name>`,
  `ASYA_SOCKET_DIR=/var/run/asya/mesh`, `ASYA_ACTOR_SINK=x-sink`,
  `ASYA_ACTOR_SUMP=x-sump`, `ASYA_NAMESPACE=local`
- Runtime env: `ASYA_HANDLER=<handler>`, `ASYA_SOCKET_DIR=/var/run/asya`
- Shared named volume `asya-mesh` at `/var/run/asya/mesh/` for all sidecars
- Shared named volume `asya-runtime-sockets` at `/var/run/asya/` for sidecar↔runtime
- Runtime depends_on sidecar (each pair)
- Drop `ASYA_STATE_PROXY_MOUNTS` — state mounts become Docker volumes
- Add `x-sink` and `x-sump` system actor services (sidecar-only, no runtime needed
  since they just ack/log)
- Compose project name: `asya-<flow-name>`
- Output path: `.asya/compose/<flow-name>.yaml`

### Step 2: `d_cli.py` — CLI commands

Argparse-based CLI (consistent with current codebase on main):
- `asya d up <target>` — resolve target, auto-compile if .py, generate compose,
  run `docker compose up -d`
- `asya d down <target>` — resolve target to compose file,
  run `docker compose down`
- `asya d send <actor> <payload>` — write JSON envelope to Unix socket
  at `/var/run/asya/mesh/<actor>.sock`
- `asya d logs <target>` — resolve to compose file,
  run `docker compose logs -f`

### Step 3: Register in cli.py

Add `d` (and `docker` alias) subcommand to the main CLI dispatcher.

### Step 4: Tests

- `test_compose.py` — unit tests for compose YAML generation (mock manifests)
- `test_d_cli.py` — CLI help, argument parsing, subprocess mocking

### Step 5: Quality gates

Run `make test-unit`, `make lint`, commit, push.

## References

- `.aint/aints/asya-lab/rfc.md` §5.3 — Docker commands
- `.aint/aints/asya-lab/rfc.md` §5.11 — testing tiers
- `.aint/aints/asya-lab/adr.k-d-command-split.md` §3 — socket transport design
- `.aint/aints/asya-lab/adr.k-d-command-split.md` §5 — Docker secrets via .env.secret
- `.aint/aints/.closed/stateful-actors/rfc.md` — state proxy design (ASYA_STATE_PROXY_MOUNTS)
