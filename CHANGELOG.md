# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial open source release of Asya framework
- Actor-based framework for serving AI workloads on Kubernetes
- CRD-based operator pattern with automatic sidecar injection
- Message queue integration (RabbitMQ, SQS)
- Event-driven autoscaling with KEDA
- MCP (Model Context Protocol) gateway
- Comprehensive documentation and examples
- Full deployment examples for Minikube
- Integration and E2E test suites

### Components
- **asya-gateway**: MCP gateway implementing JSON-RPC 2.0 over HTTP
- **asya-sidecar**: Go sidecar for queue consumption
- **asya-runtime**: Python base library for actor processing logic
- **asya-operator**: Kubernetes operator for AsyncActor CRDs

### Infrastructure
- Helm charts for deployment
- Docker images for all components
- GitHub Actions CI/CD pipeline
- Automated testing and security scanning

## [0.1.0] - 2025-01-XX

### Added
- Initial internal development version

---

## Release Process

1. Update version numbers in relevant files
2. Update this CHANGELOG.md with new version
3. Create a git tag: `git tag -a v1.0.0 -m "Release v1.0.0"`
4. Push tag: `git push origin v1.0.0`
5. GitHub Actions will automatically create release and build artifacts