# Getting Started with Asya🎭

Step-by-step guide to onboarding your project on Asya🎭.

## Overview

Asya🎭 is an async actor-based framework for deploying AI workloads on Kubernetes with KEDA autoscaling and scale-to-zero capabilities.

**Total time to first deployment: ~70 minutes**

---

## Step 1: Evaluate Fit (10 min)

**Goal:** Determine if Asya🎭 is the right choice for your project.

**What you'll learn:**
- When to use async actors vs HTTP services
- Architecture trade-offs (latency vs resilience)
- Prerequisites and infrastructure requirements

**Action:**
1. Read [01. Onboarding Guide](01-onboarding.md) sections:
   - [Should I Use Asya🎭?](01-onboarding.md#should-i-use-asya)
   - [Architecture Decision](01-onboarding.md#architecture-decision)
   - [Prerequisites](01-onboarding.md#prerequisites)

**Optional deep dive:**
- [Architecture Motivation](../architecture/README.md#motivation) - Detailed comparison with sync/async patterns

**Decision point:** ✅ If Asya🎭 fits your use case, continue to Step 2.

---

## Step 2: Understand Core Concepts (15 min)

**Goal:** Learn how Asya🎭 works: actors, envelopes, routing, scaling.

**What you'll learn:**
- Actor model and sidecar pattern
- Envelope structure and message flow
- Automatic routing and end queues
- KEDA autoscaling behavior

**Action:**
1. Read [02. Core Concepts](02-concepts.md):
   - [Actor](02-concepts.md#actor) - Computational units
   - [Sidecar Pattern](02-concepts.md#sidecar-pattern) - Runtime isolation
   - [Message Flow](02-concepts.md#message-flow) - Queue → Sidecar → Runtime → Queue
   - [Routes](02-concepts.md#routes) - Pipeline definition
   - [Autoscaling](02-concepts.md#autoscaling) - KEDA integration

**Optional deep dive:**
- [Architecture Overview](../architecture/README.md) - System architecture
- [Envelope Protocol](../architecture/protocol-envelope.md) - Message format details
- [Sidecar-Runtime Protocol](../architecture/protocol-unix-socket.md) - Unix socket communication

**Checkpoint:** ✅ You understand how messages flow through actors and how scaling works.

---

## Step 3: Install Asya🎭 (30 min)

**Goal:** Deploy Asya🎭 operator and infrastructure on Kubernetes.

**What you'll do:**
- Set up Kubernetes cluster (or use existing)
- Install CRDs and operator
- Deploy message transport (RabbitMQ)
- Optionally install KEDA, gateway, monitoring

**Action:**
1. Follow [03. Installation Guide](03-installation.md)

**Quick path (recommended for evaluation):**
```bash
cd examples/deployment-minikube
./deploy.sh      # Full stack with RabbitMQ, KEDA, monitoring
./test-e2e.sh    # Verify deployment
```

**Manual path (for production):**
- [Install CRDs](03-installation.md#step-1-install-crds)
- [Install Operator](03-installation.md#step-2-install-operator)
- [Install Gateway](03-installation.md#step-3-install-gateway-optional) (optional)
- [Install KEDA](03-installation.md#step-4-install-keda-optional) (optional)

**Optional deep dive:**
- [Operator Component](../architecture/asya-operator.md) - How operator works
- [Gateway Component](../architecture/asya-gateway.md) - MCP gateway architecture
- [Transport Configuration](../architecture/transport.md) - RabbitMQ setup

**Checkpoint:** ✅ Operator is running, CRDs are installed, transport is available.

---

## Step 4: Deploy Your First Actor (15 min)

**Goal:** Create and deploy a simple AsyncActor.

**What you'll do:**
- Write AsyncActor YAML manifest
- Deploy to Kubernetes
- Verify actor creation and scaling

**Action:**
1. Follow [04. Quick Start](04-quickstart.md):
   - [Deploy Your First Actor](04-quickstart.md#deploy-your-first-actor)
   - Check status with `kubectl get asyas`
   - Verify created resources (Deployment, ScaledObject)

**AsyncActor template:**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-runtime:latest
          env:
          - name: ASYA_HANDLER
            value: "my_module.process"
```

**Optional deep dive:**
- [AsyncActor CRD Reference](../architecture/asya-operator.md#asyncactor-crd-api-reference) - Complete YAML specification
- [Example Actors](../guides/examples-actors.md) - More complex examples
- [Runtime Component](../architecture/asya-runtime.md) - Handler development

**Checkpoint:** ✅ Your first actor is deployed and scaling.

---

## Step 5: Understand Behavior (refer as needed)

**Goal:** Know how actors behave in production.

**What you'll learn:**
- Scaling timeline and cold starts
- Error handling and retries
- Route modification rules
- Integration patterns

**Action:**
1. Refer to [01. Onboarding Guide](01-onboarding.md) sections as needed:
   - [Actor Behavior](01-onboarding.md#actor-behavior) - Message flow, routing, scaling
   - [Error Handling](01-onboarding.md#error-handling) - Retries, timeouts, DLQ
   - [Integration Patterns](01-onboarding.md#integration-patterns) - API gateway, direct queue, hybrid
   - [Common Gotchas](01-onboarding.md#common-gotchas) - Avoid common mistakes

**Optional deep dive:**
- [Sidecar Component](../architecture/asya-sidecar.md) - Sidecar internals
- [Metrics Reference](../architecture/observability.md) - Observability

**Checkpoint:** ✅ You understand production behavior and edge cases.

---

## Next Steps

### For Developers
- [Example Deployments](../guides/examples-deployments.md) - Production-ready examples
- [Building Guide](../guides/building.md) - Build custom runtime images
- [Development Guide](../guides/development.md) - Contribute to Asya🎭

### For Operators
- [Deployment Guide](../guides/deploy.md) - Production deployment strategies
- [Metrics Reference](../architecture/observability.md) - Monitoring and alerting
- [Testing Guide](../guides/testing.md) - Integration testing

### For Architects
- [Design Rationale](../architecture/design-rationale.md) - Why certain decisions were made
- [Component Architecture](../architecture/README.md) - Deep dive into each component

---

## Quick Reference

**Essential commands:**
```bash
# List all actors
kubectl get asyas -A

# Describe actor
kubectl describe asya my-actor

# Check workload
kubectl get deployment my-actor

# Check scaling
kubectl get scaledobject my-actor

# View logs
kubectl logs -l app=my-actor -c sidecar
kubectl logs -l app=my-actor -c runtime
```

**AsyncActor minimal YAML:**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-actor
spec:
  transport: rabbitmq
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
  workload:
    type: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-runtime:latest
          env:
          - name: ASYA_HANDLER
            value: "module.function"
```

**Envelope structure:**
```json
{
  "id": "envelope-id",
  "route": {"actors": ["actor1", "actor2"], "current": 0},
  "headers": {"trace_id": "..."},
  "payload": {"your": "data"}
}
```

---

## Support

- **Issues**: [GitHub Issues](https://github.com/your-org/asya/issues)
- **Documentation**: [docs/](../)
- **Examples**: [examples/](../../examples/)
