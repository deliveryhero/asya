---
title: "CLI: asya d up/down/send/logs (Docker Compose local testing)"
priority: 2 # medium
---

## Scope

Implement Docker Compose commands for local testing:

### asya d up <target>

1. Auto-compile if given `.py` file
2. Generate `docker-compose.yaml` from compiled manifests
3. Each actor gets: sidecar container + runtime container (same architecture as K8s)
4. Socket transport (`ASYA_TRANSPORT=socket`) for inter-actor communication
5. Shared Docker volume at `/var/run/asya/mesh/` for Unix sockets
6. `docker compose up -d`

### asya d down <target>

- `docker compose down` for the flow's compose project

### asya d send <target> '{}'

- Write envelope to actor's Unix socket

### asya d logs <target>

- `docker compose logs -f`

### Two testing tiers

| Tier | What runs | Transport |
|------|-----------|-----------|
| Single actor | `asya d up <actor.py>` | HTTP (runtime as server) |
| Full flow | `asya d up <flow.py>` | Socket (sidecar + runtime per actor) |

### Secrets handling

When `asya d up` detects env vars mapped to K8s secrets, it checks `.env.secret`.
Missing = error with hint to `asya k secret show -o env >> .env.secret`.

## Dependencies

- [cavw] Socket transport implementation in sidecar (Go)
- [5ifn] Compile command
- [hox4] Manifest stamping

## References

- `.aint/aints/asya-lab/rfc.md` §5.3 — Docker commands
- `.aint/aints/asya-lab/rfc.md` §5.11 — testing tiers
- `.aint/aints/asya-lab/adr.k-d-command-split.md` §3 — socket transport design
- `.aint/aints/asya-lab/adr.k-d-command-split.md` §5 — Docker secrets via .env.secret
