# Asya🎭 Documentation

Meet Asya🎭 - a new open-source Kubernetes-native **async actor framework** for orchestrating AI/ML workloads at scale.

GitHub repo: [https://github.com/deliveryhero/asya](https://github.com/deliveryhero/asya) ⭐

<div style="width: 100%;">
<img src="./img/asya-full.jpg" alt="Asya image" width="50%"/>
<p style="font-size: 0.7em; font-style: italic; color: #666; margin-top: -2px;">Image generated with OpenAI</p>
</div>

## Documentation Structure

### Getting Started
- **[Motivation](motivation.md)** - Why Asya exists, problems it solves, when to use it
- **[Core Concepts](concepts.md)** - Actors, envelopes, sidecars, runtime, and system components

### Architecture
- **[Architecture Overview](architecture/README.md)** - Deep dive into system design and components
  - [Actors](architecture/asya-actor.md) - Stateless workloads with message-based communication
  - [Sidecar](architecture/asya-sidecar.md) - Message routing and transport management
  - [Runtime](architecture/asya-runtime.md) - User code execution environment
  - [Operator](architecture/asya-operator.md) - Kubernetes CRD controller
  - [Gateway](architecture/asya-gateway.md) - Optional MCP HTTP API
  - [Crew](architecture/asya-crew.md) - System actors for flow maintenance
  - [Autoscaling](architecture/autoscaling.md) - KEDA integration details
  - [Protocols](architecture/protocols/actor-actor.md) - Communication protocols between components
  - [Transports](architecture/transports/README.md) - Message queue implementations

### Installation
- **[AWS EKS](install/aws-eks.md)** - Production deployment on AWS
- **[Local Kind](install/local-kind.md)** - Local development cluster
- **[Helm Charts](install/helm-charts.md)** - Chart configuration reference

### Quickstart
- **[For Data Scientists](quickstart/for-data-scientists.md)** - Build and deploy your first actor
- **[For Platform Engineers](quickstart/for-platform-engineers.md)** - Deploy and manage Asya infrastructure

### Operations
- **[Monitoring](operate/monitoring.md)** - Observability and metrics
- **[Troubleshooting](operate/troubleshooting.md)** - Common issues and solutions
- **[Upgrades](operate/upgrades.md)** - Version upgrade procedures

## Quick Links

- [GitHub Repository](https://github.com/deliveryhero/asya)
- [Examples](https://github.com/deliveryhero/asya/tree/main/examples)
- [Contributing Guide](https://github.com/deliveryhero/asya/blob/main/CONTRIBUTING.md)
