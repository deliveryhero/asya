# Asya Framework Documentation

Async actor-based framework for serving AI workloads on Kubernetes.

## Overview

Asya provides a CRD-based operator pattern for deploying AI actors with automatic sidecar injection, message queue integration, and event-driven autoscaling.

## Quick Start

### Option 1: Full OSS Stack (Recommended for Testing)

Complete deployment with RabbitMQ, Prometheus, Grafana, and example actors:

```bash
cd examples/deployment-minikube
./deploy.sh      # Automated deployment (~5-10 minutes)
./test-e2e.sh        # Verify deployment
```

### Option 2: Minimal Framework Only

Install just the Asya operator and CRDs:

```bash
# 1. Install CRDs
kubectl apply -f operator/config/crd/

# 2. Install operator
helm install asya-operator deploy/helm-charts/asya-operator --create-namespace -n asya-system

# 3. Deploy an actor (requires existing queue)
kubectl apply -f examples/asyas/simple-actor.yaml
```

## Documentation

### Getting Started
- [Quick Start](getting-started/quickstart.md) - Get up and running quickly
- [Installation](getting-started/installation.md) - Detailed installation guide
- [Concepts](getting-started/concepts.md) - Core concepts and terminology

### Components
- [Asya Gateway](components/gateway.md) - MCP gateway with job management
- [Asya Sidecar](components/sidecar.md) - Message routing and queue integration
- [Asya Runtime](components/runtime.md) - Actor runtime base library
- [Asya Operator](components/operator.md) - Kubernetes operator and CRD

### Architecture
- [Overview](architecture/overview.md) - High-level architecture
- [Design Rationale](architecture/design-rationale.md) - Why sidecar and async?
- [Sidecar Architecture](architecture/sidecar.md) - Detailed sidecar design
- [Message Flow](architecture/messages.md) - Message routing and processing

### Guides
- [Building Images](guides/building.md) - Building and packaging
- [Deployment](guides/deployment.md) - Deployment strategies
- [Testing](guides/testing.md) - Testing your actors
- [Development](guides/development.md) - Local development workflow

### Reference
- [Metrics](reference/metrics.md) - Prometheus metrics reference
- [Scripts](reference/scripts.md) - Build and deployment scripts
- [API Reference](reference/api.md) - AsyncActor CRD API specification

### Examples
- [Actor Examples](examples/actors.md) - Example actor configurations
- [Deployment Examples](examples/deployments.md) - Reference deployments

## Key Features

- **CRD-Based Operator**: Declarative actor deployment with automatic sidecar injection
- **Multiple Queue Systems**: Support for RabbitMQ (AWS SQS support removed)
- **Event-Driven Autoscaling**: KEDA integration for queue-based scaling
- **MCP Gateway**: Model Context Protocol support with job tracking and SSE streaming
- **Monitoring**: Prometheus metrics and Grafana dashboards
- **Flexible Workloads**: Support for Deployments, StatefulSets, and Jobs

## Repository Structure

```
asya-prototype/
├── src/                     # Framework components
│   ├── asya-gateway/        # MCP gateway (Go)
│   ├── asya-sidecar/        # Actor sidecar (Go)
│   ├── asya-runtime/        # Actor runtime base (Python)
│   └── asya-otel-sidecar/   # OpenTelemetry sidecar (Python)
├── operator/                # Kubernetes operator source
├── deploy/                  # Helm charts for deployment
├── examples/                # Example deployments and actors
├── scripts/                 # Build and deployment scripts
└── docs/                    # Documentation (you are here)
```

## Community

- GitHub: [asya-prototype](https://github.com/gh-aimc/asya-prototype)
- Issues: [Report bugs or request features](https://github.com/gh-aimc/asya-prototype/issues)

## License

See [LICENSE](../LICENSE)
