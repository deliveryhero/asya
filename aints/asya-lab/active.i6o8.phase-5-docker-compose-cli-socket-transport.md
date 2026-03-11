---
title: "Phase 5: Docker Compose CLI + socket transport"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/.worktrees/asya-lab/i6o8.phase-5-docker-compose-cli-socket-transport
  - branch:asya-lab/i6o8.phase-5-docker-compose-cli-socket-transport
dependencies:
  - 5ifn
  - cavw
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

## References

- `.aint/aints/asya-lab/rfc.md` §5.3 — Docker commands
- `.aint/aints/asya-lab/rfc.md` §5.11 — testing tiers
- `.aint/aints/asya-lab/adr.k-d-command-split.md` §3 — socket transport design
- `.aint/aints/asya-lab/adr.k-d-command-split.md` §5 — Docker secrets via .env.secret
