<!-- Type: Explanation -->
# Asya🎭 Documentation

Meet Asya🎭 - a new open-source Kubernetes-native **async actor framework** for orchestrating AI/ML workloads at scale.

GitHub repo: [https://github.com/deliveryhero/asya](https://github.com/deliveryhero/asya) ⭐

<img src="./img/logo_colored_with_borders.png" alt="Asya" width="280"/>

## Start Here

| I want to... | Start with |
|---|---|
| Understand what Asya is | [Motivation](motivation.md) then [Core Concepts](concepts.md) |
| Get a local cluster running | [Quickstart Setup](quickstart/README.md) |
| Build my first actor | [Tutorial: First Actor](tutorials/first-actor.md) |
| Chain actors into a pipeline | [Tutorial: First Pipeline](tutorials/first-pipeline.md) |
| Write a Flow DSL pipeline | [Tutorial: First Flow](tutorials/first-flow.md) |
| Deploy to production | [AWS EKS](install/aws-eks.md) or [GCP GKE](install/gcp-gke.md) |
| Look up configuration | [Reference](#reference) section below |
| Understand design decisions | [Explanation](#explanation) section below |

## Documentation Structure

### Tutorials

Learn by doing — step-by-step guides with verifiable outcomes.

- **[First Actor](tutorials/first-actor.md)** - Build, deploy, and test a minimal actor
- **[First Pipeline](tutorials/first-pipeline.md)** - Chain two actors and trace envelope routing
- **[First Flow](tutorials/first-flow.md)** - Write a Flow DSL file, compile, and deploy
- **[Pause/Resume](tutorials/pause-resume.md)** - Add human-in-the-loop to a pipeline
- **[Actor Handler Adapter Pattern](tutorials/actor-handler-adapter-pattern.md)** - Wrap third-party models with a clean handler interface
- **[Actor Flavors](tutorials/actor-flavors.md)** - Type-aware merge and actor variant configuration
- **[Agentic Patterns](tutorials/agentic-patterns.md)** - Fan-out, dynamic routing, streaming, pause/resume

### How-to Guides

Task-oriented — practical steps to achieve a specific goal.

- **[Add a New Actor](howto/add-new-actor.md)** - Write handler, create manifest, deploy, verify
- **[Debug an Envelope](howto/debug-envelope.md)** - Trace envelopes through the mesh
- **[Configure Retries](howto/configure-retries.md)** - Set up retry policies and error matching
- **[Set Up Pause/Resume](howto/setup-pause-resume.md)** - Route configuration for human-in-the-loop
- **[Configure Autoscaling](howto/configure-autoscaling.md)** - KEDA per-actor queue-depth scaling
- **[Register Gateway Tools](howto/register-gateway-tools.md)** - ConfigMap-based tool registration

### Architecture
- **[Overview](architecture/README.md)** - System design and component interactions
  - [Actors](architecture/asya-actor.md) - Stateless workloads with message-based communication
  - [Sidecar](architecture/asya-sidecar.md) - Message routing and transport management
  - [Runtime](architecture/asya-runtime.md) - User code execution environment
  - [Crossplane Compositions](architecture/asya-crossplane.md) - Declarative resource management
  - [Gateway](architecture/asya-gateway.md) - MCP / A2A / HTTP bridge to the async mesh
  - [Crew](architecture/asya-crew.md) - Built-in system actors (x-sink, x-sump, x-pause, x-resume)
  - [Flow Compiler](architecture/asya-flow.md) - How Flow DSL transforms Python into actor networks
  - [State Proxy](architecture/asya-state-proxy.md) - Virtual persistent state for stateless actors
  - [CLI Tools](reference/cli.md) - `asya flow`, `asya mcp`, `asya build`, `asya k`
  - [Autoscaling](howto/configure-autoscaling.md) - KEDA per-actor queue-depth scaling
  - [Observability](architecture/observability.md) - Metrics, tracing, Prometheus/Grafana
- **Protocols**
  - [Actor-Actor](architecture/protocols/actor-actor.md) - Envelope spec and payload enrichment
  - [Sidecar-Runtime](architecture/protocols/sidecar-runtime.md) - Unix socket ABI between sidecar and runtime
- **Transports**
  - [SQS](architecture/transports/sqs.md) - AWS SQS / LocalStack configuration
  - [RabbitMQ](architecture/transports/rabbitmq.md) - RabbitMQ configuration
  - [All transports](architecture/transports/README.md) - Transport comparison and selection

### Reference

Accurate technical descriptions — specs, configuration tables, API surfaces.

- **[ABI Yield Protocol](reference/abi-protocol.md)** - Generator handler yield forms (GET, SET, FLY)
- **[Flow DSL](reference/flow-dsl.md)** - Flow DSL syntax, supported constructs, and compilation rules
- **[AsyncActor CRD](reference/asyncactor-crd.md)** - Full CRD field reference
- **[Environment Variables](reference/env-vars.md)** - Consolidated env var reference across all components
- **[CLI Reference](reference/cli.md)** - `asya flow`, `asya mcp`, `asya build`, `asya k`
- **[Agentic Cheatsheet](reference/agentic-cheatsheet.md)** - ADK-to-Asya pattern mapping
- **[Helm Charts](install/helm-charts.md)** - Chart configuration reference

### Explanation

Understanding-oriented — design rationale and background context.

- **[Motivation](motivation.md)** - Why async choreography over centralized orchestration
- **[Core Concepts](concepts.md)** - Envelope, actor, sidecar, runtime, crew, flow DSL, gateway
- **[Choreography vs Orchestration](explanation/choreography-vs-orchestration.md)** - Trade-offs and when to use each
- **[Envelope Design](explanation/envelope-design.md)** - Why route.prev/curr/next, immutable IDs, opaque payload
- **[Flow Compilation](explanation/flow-compilation.md)** - How the compiler transforms Python to CPS message chains
- **[Agentic Design](explanation/agentic-design.md)** - How Asya maps to agentic patterns

### Installation
- **[Local Kind](install/local-kind.md)** - Local development cluster setup
- **[AWS EKS](install/aws-eks.md)** - Production deployment on AWS
- **[GCP GKE](install/gcp-gke.md)** - Production deployment on GCP
- **[Helm Charts](install/helm-charts.md)** - Chart configuration reference

### Operations
- **[Scaling](howto/configure-autoscaling.md)** - KEDA config, GPU workloads, cost optimization
- **[Monitoring](operate/monitoring.md)** - Dashboards, alerts, metrics
- **[Troubleshooting](operate/troubleshooting.md)** - Common issues and solutions
- **[Upgrades](operate/upgrades.md)** - Version upgrade procedures

## Quick Links

- [GitHub Repository](https://github.com/deliveryhero/asya)
- [Examples](https://github.com/deliveryhero/asya/tree/main/examples)
- [Contributing Guide](https://github.com/deliveryhero/asya/blob/main/CONTRIBUTING.md)
