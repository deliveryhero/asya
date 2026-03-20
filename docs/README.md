# Asya Documentation

Asya is an open-source Kubernetes-native **async actor framework** for orchestrating AI/ML workloads at scale.

GitHub repo: [https://github.com/deliveryhero/asya](https://github.com/deliveryhero/asya)

<img src="website/img/logo_colored_with_borders.png" alt="Asya" width="280"/>

## Build AI Actors

```python
async def handler(payload):
    result = await my_model.predict(payload["input"])
    return {"prediction": result}
```

Write a Python function, deploy as a Kubernetes actor, chain into meshes.
**[Start building ->](usage/README.md)**

## Run the Platform

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-model
spec:
  image: my-model:latest
  handler: handler.py
  scaling:
    queueLength: 5
```

Deploy Asya on your cluster, configure transports, monitor and scale.
**[Set up Asya ->](setup/README.md)**

---

## Start Here

| I want to... | Start with |
|---|---|
| Understand what Asya is | [Motivation](motivation.md) then [Core Concepts](concepts.md) |
| Get a local cluster running | [Quickstart](setup/start-quickstart.md) |
| Build my first actor | [First Actor](usage/start-first-actor.md) |
| Chain actors into a mesh | [First Actor Mesh](usage/start-first-actor-mesh.md) |
| Write a Flow DSL | [First Flow](usage/start-first-flow.md) |
| Deploy to production | [AWS EKS](setup/start-aws-eks.md) or [GCP GKE](setup/start-gcp-gke.md) |
| Look up configuration | [Reference](reference/README.md) |

## Documentation Map

### Concepts

- **[Motivation](motivation.md)** — Why async choreography over centralized orchestration
- **[Core Concepts](concepts.md)** — Actor mesh, envelope, sidecar, runtime, crew, flow DSL, gateway
- **[Architecture](architecture.md)** — System design, component interactions, sync gateway

### Usage (Actor Authors)

Build, compose, and debug actors. **[Full index ->](usage/README.md)**

- [First Actor](usage/start-first-actor.md) | [First Mesh](usage/start-first-actor-mesh.md) | [First Flow](usage/start-first-flow.md)
- [Handler Patterns](usage/guide-handler-patterns.md) | [Agentic Patterns](usage/guide-agentic-patterns.md) | [Streaming](usage/guide-streaming.md)
- [Pause/Resume](usage/guide-pause-resume.md) | [State Proxy](usage/guide-state-proxy.md) | [Timeouts](usage/guide-timeouts.md)

### Setup (Platform Engineers)

Deploy, configure, and operate. **[Full index ->](setup/README.md)**

- [Quickstart](setup/start-quickstart.md) | [AWS EKS](setup/start-aws-eks.md) | [GCP GKE](setup/start-gcp-gke.md)
- [Helm Charts](setup/guide-helm-charts.md) | [Autoscaling](setup/guide-autoscaling.md) | [Gateway](setup/guide-gateway.md)
- [Monitoring](setup/ops-observability.md) | [Troubleshooting](setup/ops-troubleshooting.md) | [Upgrades](setup/ops-upgrades.md)

### Reference

Technical specifications shared by both audiences. **[Full index ->](reference/README.md)**

- **Components**: [Sidecar](reference/components/core-sidecar.md) | [Runtime](reference/components/core-runtime.md) | [Gateway](reference/components/core-gateway.md) | [Crew](reference/components/core-crew.md) | [Crossplane](reference/components/core-crossplane.md) | [Flow Compiler](reference/components/lab-flow-compiler.md) | [CLI](reference/components/lab-cli.md)
- **Specs**: [Envelope](reference/specs/envelope.md) | [ABI Protocol](reference/specs/abi-protocol.md) | [Flow DSL](reference/specs/flow-dsl.md) | [Gateway API](reference/specs/gateway-api.md) | [CRD](reference/specs/asyncactor-crd.md)
- **Transports**: [SQS](reference/transports/sqs.md) | [RabbitMQ](reference/transports/rabbitmq.md) | [Overview](reference/transports/README.md)
- [Environment Variables](reference/env-vars.md)

### Contributing

- **[Test Strategy](contributing/README.md)** — Transport, state proxy, and A2A test guides

## Quick Links

- [GitHub Repository](https://github.com/deliveryhero/asya)
- [Examples](https://github.com/deliveryhero/asya/tree/main/examples)
- [Contributing Guide](https://github.com/deliveryhero/asya/blob/main/CONTRIBUTING.md)
