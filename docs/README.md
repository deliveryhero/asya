# Asya🎭 Documentation

Welcome to Asya🎭—a Kubernetes-native async actor framework for orchestrating AI/ML workloads at scale.

## Documentation Structure

### Getting Started
- **[Motivation](motivation.md)** - Why Asya exists, problems it solves, when to use it
- **[Core Concepts](concepts.md)** - Actors, envelopes, sidecars, runtime, and system components

### Architecture
- **[Architecture Overview](architecture/)** - Deep dive into system design and components
  - [Actors](architecture/asya-actor.md) - Stateless workloads with message-based communication
  - [Sidecar](architecture/asya-sidecar.md) - Message routing and transport management
  - [Runtime](architecture/asya-runtime.md) - User code execution environment
  - [Operator](architecture/asya-operator.md) - Kubernetes CRD controller
  - [Gateway](architecture/asya-gateway.md) - Optional MCP HTTP API
  - [Crew](architecture/asya-crew.md) - System actors for flow maintenance
  - [Autoscaling](architecture/autoscaling.md) - KEDA integration details
  - [Protocols](architecture/protocols/) - Communication protocols between components
  - [Transports](architecture/transports/) - Message queue implementations

### Installation
- **[AWS EKS](install/aws-eks.md)** - Production deployment on AWS
- **[Local Kind](install/local-kind.md)** - Local development cluster
- **[Helm Charts](install/helm-charts.md)** - Chart configuration reference

### Quickstart
- **[For Data Scientists](quickstart/for-data_scientists.md)** - Build and deploy your first actor
- **[For Platform Engineers](quickstart/for-platform_engineers.md)** - Deploy and manage Asya infrastructure

### Operations
- **[Monitoring](operate/monitoring.md)** - Observability and metrics
- **[Troubleshooting](operate/troubleshooting.md)** - Common issues and solutions
- **[Upgrades](operate/upgrades.md)** - Version upgrade procedures

## Quick Links

- [GitHub Repository](https://github.com/deliveryhero/asya)
- [Examples](../examples/)
- [Contributing Guide](../CONTRIBUTING.md)
