# Internal Documentation

Dry technical notes for contributors and AI agents working on the Asya framework.
These documents capture implementation details, lessons learned, and non-obvious
decisions that would otherwise require re-reading large PRs.

## Index

| Document | Covers |
|----------|--------|
| [testing-e2e-transport.md](testing-e2e-transport.md) | How transports are wired into E2E tests: profiles, emulators, Crossplane compositions, skip logic |
| [testing-e2e-state-proxy.md](testing-e2e-state-proxy.md) | How storage backends (S3/GCS) are wired into E2E tests: crew persistence, Helm values, emulators |

## What belongs here

- Subsystem architecture decisions that are not obvious from the code
- Pitfalls and non-obvious invariants discovered during development
- "Why does X work this way?" answers for recurring questions
- Cross-cutting concerns that span multiple components or test levels

## What does NOT belong here

- User-facing docs (put those in `docs/` root or `docs/architecture/`)
- API references (put in `docs/reference/`)
- How-to guides for operators (put in `docs/operate/`)
