# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[Unreleased]: https://github.com/deliveryhero/asya/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/deliveryhero/asya/releases/tag/v0.1.0
