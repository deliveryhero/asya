# ADR: Git State Proxy Over Git-Sync

**Status:** Accepted
**Date:** 2026-04-15

## Context

Actors need code from a git repo. Two approaches:
1. git-sync init container (K8s-native, clones once at startup, read-only)
2. git state proxy (Asya-native, mounts branch as FS, read-write)

## Decision

Use **git state proxy** as the default code delivery mechanism.

Git-sync remains available as a fallback for performance-sensitive cases (high
file write frequency where commit-per-write is too slow).

## Rationale

- **Unified data channel**: state proxy + payload are the two data channels.
  Adding git-sync creates a third, increasing cognitive and operational complexity.
- **Read-write**: git state proxy supports writes (commit + push), enabling
  orchestrators to modify code and have x-deploy pick it up.
- **FS-like interface**: consistent with Design Principle 001 — actors use
  `open()` to read/write code, same as datasets and metrics.
- **Git-aint specialization**: git-aint state proxy is just git state proxy
  with a pre-commit hook running `git aint auto-state`. One implementation,
  two use cases.

## Consequences

- Write performance may be slower than local FS (each write = commit + push)
- For read-heavy workloads, sidecar caches locally after initial clone
- If write performance becomes a bottleneck, add batched commit mode
  (accumulate writes, commit on flush/close)
