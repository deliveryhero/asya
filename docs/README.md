<!-- Type: Explanation -->
# Asya Documentation

Asya is an open-source Kubernetes-native **async actor framework** for orchestrating AI/ML workloads at scale.

GitHub repo: [https://github.com/deliveryhero/asya](https://github.com/deliveryhero/asya)

<img src="./img/logo_colored_with_borders.png" alt="Asya" width="280"/>

## Start Here

| If you want to... | Start with |
|---|---|
| Understand why Asya exists | [Motivation](motivation.md) -- why async choreography beats centralized orchestration |
| Learn the core concepts | [Core Concepts](concepts.md) -- envelope, actor, sidecar, runtime, crew, flow DSL, gateway |
| Set up a local cluster | [Quickstart](quickstart/README.md) -- install Asya locally with Kind in 5 minutes |
| Build your first actor | [First Actor](tutorials/first-actor.md) -- write a handler, deploy it, send a message |
| Deploy to production | [AWS EKS](install/aws-eks.md) or [GCP GKE](install/gcp-gke.md) -- production installation guides |
| Find configuration details | [Reference](#reference) -- ABI protocol, Flow DSL, Helm charts, scaling parameters |
| Understand the architecture | [Explanation](#explanation) -- design decisions, component deep-dives, protocol specs |

## Documentation by Category

### Tutorials -- Learning-oriented

Step-by-step lessons for building with Asya.

- **[Quickstart Setup](quickstart/README.md)** -- Install Asya locally with Kind in 5 minutes
- **[Quickstart Usage](quickstart/usage.md)** -- Write handlers, deploy actors, build multi-step flows
- **[Actor Handler Adapter Pattern](tutorials/actor-handler-adapter-pattern.md)** -- Wrap third-party models with a clean handler interface
- **[Actor Flavors](tutorials/actor-flavors.md)** -- Type-aware merge and actor variant configuration
- **[Agentic Patterns](tutorials/agentic-patterns.md)** -- Build agentic systems (multi-turn, tool use, pause/resume)

### How-to Guides -- Task-oriented

Practical steps for specific goals.

- **[Install on Local Kind](install/local-kind.md)** -- Local development cluster setup
- **[Install on AWS EKS](install/aws-eks.md)** -- Production deployment on AWS
- **[Install on GCP GKE](install/gcp-gke.md)** -- Production deployment on GCP
- **[Troubleshooting](operate/troubleshooting.md)** -- Common issues and solutions
- **[Upgrades](operate/upgrades.md)** -- Version upgrade procedures

### Reference -- Information-oriented

Precise specifications and configuration details.

- **[ABI Yield Protocol](reference/abi-protocol.md)** -- Generator handler yield forms (GET, SET, FLY)
- **[Flow DSL](reference/flow-dsl.md)** -- Flow DSL syntax, supported constructs, and compilation rules
- **[Helm Charts](install/helm-charts.md)** -- Chart configuration reference
- **[Scaling](operate/scaling.md)** -- KEDA config, GPU workloads, cost optimization
- **[Monitoring](operate/monitoring.md)** -- Dashboards, alerts, metrics
- **[Resiliency](features/resiliency.md)** -- Retry policies, error handling, dead-letter queues

### Explanation -- Understanding-oriented

Background, design decisions, and architecture deep-dives.

- **[Motivation](motivation.md)** -- Why async choreography over centralized orchestration
- **[Core Concepts](concepts.md)** -- Envelope, actor, sidecar, runtime, crew, flow DSL, gateway
- **[Architecture Overview](architecture/README.md)** -- System design and component interactions
  - [Actors](architecture/asya-actor.md) -- Stateless workloads with message-based communication
  - [Sidecar](architecture/asya-sidecar.md) -- Message routing and transport management
  - [Runtime](architecture/asya-runtime.md) -- User code execution environment
  - [Crossplane Compositions](architecture/asya-crossplane.md) -- Declarative resource management
  - [Gateway](architecture/asya-gateway.md) -- MCP / A2A / HTTP bridge to the async mesh
  - [Crew](architecture/asya-crew.md) -- Built-in system actors (x-sink, x-sump, x-pause, x-resume)
  - [Flow Compiler](architecture/asya-flow.md) -- How Flow DSL transforms Python into actor networks
  - [State Proxy](architecture/asya-state-proxy.md) -- Virtual persistent state for stateless actors
  - [CLI Tools](architecture/asya-lab.md) -- `asya flow`, `asya mcp`, `asya build`, `asya k`
  - [Autoscaling](architecture/autoscaling.md) -- KEDA per-actor queue-depth scaling
  - [Observability](architecture/observability.md) -- Metrics, tracing, Prometheus/Grafana
- **Protocols**
  - [Actor-Actor](architecture/protocols/actor-actor.md) -- Envelope spec and payload enrichment
  - [Sidecar-Runtime](architecture/protocols/sidecar-runtime.md) -- Unix socket ABI between sidecar and runtime
- **Transports**
  - [SQS](architecture/transports/sqs.md) -- AWS SQS / LocalStack configuration
  - [RabbitMQ](architecture/transports/rabbitmq.md) -- RabbitMQ configuration
  - [All transports](architecture/transports/README.md) -- Transport comparison and selection
- **[Task Pause/Resume](features/task-pause.md)** -- Human-in-the-loop checkpoint and resume

## Quick Links

- [GitHub Repository](https://github.com/deliveryhero/asya)
- [Examples](https://github.com/deliveryhero/asya/tree/main/examples)
- [Contributing Guide](https://github.com/deliveryhero/asya/blob/main/CONTRIBUTING.md)
