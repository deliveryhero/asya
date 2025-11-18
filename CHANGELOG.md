# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[Unreleased]: https://github.com/deliveryhero/asya/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/deliveryhero/asya/releases/tag/v0.1.1

