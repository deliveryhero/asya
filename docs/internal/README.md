# Internal Documentation

Dry technical notes for contributors and AI agents working on the Asya framework.
These documents capture implementation details, lessons learned, and non-obvious
decisions that would otherwise require re-reading large PRs.

## Index

| Document | Covers |
|----------|--------|
| [testing-transport.md](testing-transport.md) | Transport backends across all test levels: unit mocks, component/integration Docker Compose profiles, E2E Kind cluster wiring, Pub/Sub emulator OAuth workaround, skip logic, how to add a new transport |
| [testing-state-proxy.md](testing-state-proxy.md) | State proxy / storage backends across all test levels: moto vs unittest.mock, component profiles, integration GCS overlay, E2E NodePort mapping, connector image loading, crew chart `persistence.*` values, how to add a new backend |

## What belongs here

- Subsystem architecture decisions that are not obvious from the code
- Pitfalls and non-obvious invariants discovered during development
- "Why does X work this way?" answers for recurring questions
- Cross-cutting concerns that span multiple components or test levels

## What does NOT belong here

- User-facing docs (put those in `docs/` root or `docs/architecture/`)
- API references (put in `docs/reference/`)
- How-to guides for operators (put in `docs/operate/`)
