# Contributing

Technical notes for contributors working on the Asya framework. These documents capture implementation details, test strategies, and non-obvious decisions.

## Test Strategy Guides

| Document | Covers |
|----------|--------|
| [testing-transport.md](testing-transport.md) | Transport backends across all test levels: unit mocks, component/integration Docker Compose profiles, E2E Kind cluster wiring, how to add a new transport |
| [testing-state-proxy.md](testing-state-proxy.md) | State proxy / storage backends across all test levels: moto vs unittest.mock, component profiles, integration GCS flavor, E2E NodePort mapping, how to add a new backend |
| [testing-a2a.md](testing-a2a.md) | A2A protocol test strategy across all levels |

## What Belongs Here

- Test strategies that span multiple components or test levels
- Subsystem architecture decisions that are not obvious from the code
- Pitfalls and non-obvious invariants discovered during development
- Cross-cutting concerns across components

## See Also

- [CONTRIBUTING.md](../../CONTRIBUTING.md) — contributor guidelines, test structure, Makefile patterns
- [AGENTS.md](../../AGENTS.md) — AI developer guidance
