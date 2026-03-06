# Internal Documentation

Dry technical notes for contributors and AI agents working on the Asya framework.
These documents capture implementation details, lessons learned, and non-obvious
decisions that would otherwise require re-reading large PRs.

## Index

### Transport backends

| Document | Scope | Covers |
|----------|-------|--------|
| [testing-transport.md](testing-transport.md) | All levels | Mock strategies per level, component/integration profiles, how to add a new transport end-to-end |
| [testing-e2e-transport.md](testing-e2e-transport.md) | E2E only | Kind NodePort mapping, Crossplane compositions, Pub/Sub emulator OAuth workaround, `gcpProject` pattern, skip logic |

### State proxy / storage backends

| Document | Scope | Covers |
|----------|-------|--------|
| [testing-state-proxy.md](testing-state-proxy.md) | All levels | Mock strategies per level (moto/unittest.mock), component profiles, integration overlays, how to add a new backend |
| [testing-e2e-state-proxy.md](testing-e2e-state-proxy.md) | E2E only | NodePort mapping, fake-gcs-server quirks, connector image loading into Kind, crew chart `persistence.*` values |

## What belongs here

- Subsystem architecture decisions that are not obvious from the code
- Pitfalls and non-obvious invariants discovered during development
- "Why does X work this way?" answers for recurring questions
- Cross-cutting concerns that span multiple components or test levels

## What does NOT belong here

- User-facing docs (put those in `docs/` root or `docs/architecture/`)
- API references (put in `docs/reference/`)
- How-to guides for operators (put in `docs/operate/`)
