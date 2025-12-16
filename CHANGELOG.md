# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]


## [0.3.1] - 2025-12-16

## Major Changes

* fix(charts): Update images repository to ghcr.io (#65) @ghost

## Other Changes

* fix(charts): Update images repository to ghcr.io (#65) @ghost
* style: Simplify css by re-using stylesheets file (#66) @ghost
* ci: Add asya-crds yaml to release artifacts (#67) @ghost

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.3.1`
- `ghcr.io/deliveryhero/asya-gateway:0.3.1`
- `ghcr.io/deliveryhero/asya-sidecar:0.3.1`
- `ghcr.io/deliveryhero/asya-crew:0.3.1`
- `ghcr.io/deliveryhero/asya-testing:0.3.1`

## Contributors

@atemate, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)



## [Unreleased]


## [0.3.0] - 2025-12-15

## Major Changes

* feat: Add basic support for flows (#58) @atemate-dh
* refactor(asya-cli)!: Consolidate tools into single `asya` CLI with subcommands (#59) @atemate-dh

## Other Changes

* docs: Add landing page for asya.sh, deploy charts to asya.sh/charts (#62) @atemate-dh
* chore: Increase verbosity of helm tests (#61) @atemate-dh
* feat: Add basic support for flows (#58) @atemate-dh
* ci: Try to fix Octocov coverage again again (#60) @atemate-dh
* refactor(asya-cli)!: Consolidate tools into single `asya` CLI with subcommands (#59) @atemate-dh

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:1.0.0`
- `ghcr.io/deliveryhero/asya-gateway:1.0.0`
- `ghcr.io/deliveryhero/asya-sidecar:1.0.0`
- `ghcr.io/deliveryhero/asya-crew:1.0.0`
- `ghcr.io/deliveryhero/asya-testing:1.0.0`

## Contributors

@atemate-dh, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)



## [Unreleased]


## [0.2.0] - 2025-12-04

## Major Changes

* feat: Implement namespace-aware queue naming (#46) @atemate-dh
* feat: Propagate labels from CR to owned resources (#45) @atemate-dh
* bug: Fix bug disallowing class handlers without a constructor (#43) @atemate-dh
* feat: Enable creation of asyas in different namespaces (#41) @atemate-dh
* fix: Put Queue deletion under `ASYA_DISABLE_QUEUE_MANAGEMENT` feature flag (#31) @atemate-dh

## Other Changes

* chore: Bump asya-gateway dep: golang.org/x/crypto 0.37.0 -> 0.45.0 (#56) @atemate-dh
* ci: Try to fix Octocov coverage again (#55) @atemate-dh
* feat: Implement namespace-aware queue naming (#46) @atemate-dh
* ci: Simplify release categories 7 (#54) @atemate-dh
* ci: Simplify release categories 6 (#53) @atemate-dh
* ci: Simplify release categories 5 (#52) @atemate-dh
* ci: Simplify release categories 4 (#51) @atemate-dh
* ci: Simplify release categories 3 (#50) @atemate-dh
* ci: Simplify release categories 2 (#49) @atemate-dh
* ci: Simplify release categories (#47) @atemate-dh
* ci: Fix octocov persistance for main branch again (#48) @atemate-dh
* feat: Propagate labels from CR to owned resources (#45) @atemate-dh
* fix: Add datastores to octocov summary section for baseline comparison (#44) @atemate-dh
* bug: Fix bug disallowing class handlers without a constructor (#43) @atemate-dh
* feat: Enable creation of asyas in different namespaces (#41) @atemate-dh
* ci: Improve PR labels (#42) @atemate-dh
* build: Adapt local setup for macOS (#36) @atemate-dh
* build: Fix CI Octocov coverage - main not saving results (#37) @atemate-dh
* build: Upgrade Go from 1.23 to 1.24 (#34) @atemate-dh
* Clarify e2e docs and dedupe platform quickstart (#29) @msaharan
* docs: Update E2E README to match current make targets (#24) @msaharan
* fix: Put Queue deletion under `ASYA_DISABLE_QUEUE_MANAGEMENT` feature flag (#31) @atemate-dh
* fix: Sidecar integration tests for macOS (#32) @atemate-dh
* fix: Enable coverage reporting for e2e tests and fix CI artifact paths (#33) @atemate-dh
* docs: Align Local Kind install guide with current e2e profiles and Helm workflow (#25) @msaharan
* chore: Fix root make test-e2e target to run actual e2e flow (#28) @msaharan
* docs: fix architecture link text in data scientists quickstart (#27) @msaharan
* fix: Delete unneeded ASYA\_SKIP\_QUEUE\_OPERATION env var (#30) @atemate-dh
* docs: Align RabbitMQ transport doc and shared compose README with current tooling (#26) @msaharan

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.2.0`
- `ghcr.io/deliveryhero/asya-gateway:0.2.0`
- `ghcr.io/deliveryhero/asya-sidecar:0.2.0`
- `ghcr.io/deliveryhero/asya-crew:0.2.0`
- `ghcr.io/deliveryhero/asya-testing:0.2.0`

## Contributors

@atemate-dh, @github-actions[bot], @msaharan and [github-actions[bot]](https://github.com/apps/github-actions)



## [Unreleased]


## [0.1.1] - 2025-11-18

## What's Changed

## Documentation

- Fix Documentation rendering, fix search @atemate-dh (#18)
- Minor: Polish documentation @atemate-dh (#16)
- feat: Update all documentation, add GitHub Pages @atemate-dh (#15)
- feat: Add queue health monitoring with automatic queue recreation @atemate-dh (#9)
- Update CHANGELOG.md for v0.1.0 @[github-actions[bot]](https://github.com/apps/github-actions) (#7)

## Testing

- fix: Update test configuration to match envelope store refactoring @atemate-dh (#17)
- feat: Update all documentation, add GitHub Pages @atemate-dh (#15)
- bug: Fix KEDA/HPA race condition @atemate-dh (#14)
- feat: Add queue health monitoring with automatic queue recreation @atemate-dh (#9)

## Infrastructure

- Fix Documentation rendering, fix search @atemate-dh (#18)
- fix: Update test configuration to match envelope store refactoring @atemate-dh (#17)
- Minor: Polish documentation @atemate-dh (#16)
- feat: Update all documentation, add GitHub Pages @atemate-dh (#15)
- feat: Add queue health monitoring with automatic queue recreation @atemate-dh (#9)

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.1.1`
- `ghcr.io/deliveryhero/asya-gateway:0.1.1`
- `ghcr.io/deliveryhero/asya-sidecar:0.1.1`
- `ghcr.io/deliveryhero/asya-crew:0.1.1`
- `ghcr.io/deliveryhero/asya-testing:0.1.1`

## Contributors

@atemate-dh, @github-actions[bot] and [github-actions[bot]](https://github.com/apps/github-actions)



## [Unreleased]


## [0.1.0] - 2025-11-17

## What's Changed

- Scaffold release CI with ghcr.io, adjust Operator resources @atemate-dh (#4)
- Improve main README.md, fix e2e tests @atemate-dh (#3)
- Add asya @atemate-dh (#2)
- Revert to initial commit state @atemate-dh (#1)

## Testing

- feat: Add error details extraction in error-end actor @atemate-dh (#6)
- fix: Sidecar should not access transport to verify queue readiness @atemate-dh (#5)

## Docker Images

All images are published to GitHub Container Registry:

- `ghcr.io/deliveryhero/asya-operator:0.1.0`
- `ghcr.io/deliveryhero/asya-gateway:0.1.0`
- `ghcr.io/deliveryhero/asya-sidecar:0.1.0`
- `ghcr.io/deliveryhero/asya-crew:0.1.0`
- `ghcr.io/deliveryhero/asya-testing:0.1.0`

## Contributors

@atemate-dh and @nmertaydin



## [Unreleased]

### Added
- CI workflow for publishing Docker images on GitHub releases
- Automated changelog generation using release-drafter
- Release workflow for building and publishing asya-* images to ghcr.io

[0.1.0]: https://github.com/deliveryhero/asya/releases/tag/v0.1.0

[0.1.1]: https://github.com/deliveryhero/asya/releases/tag/v0.1.1


[0.2.0]: https://github.com/deliveryhero/asya/releases/tag/v0.2.0


[0.3.0]: https://github.com/deliveryhero/asya/releases/tag/v0.3.0


[Unreleased]: https://github.com/deliveryhero/asya/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/deliveryhero/asya/releases/tag/v0.3.1

