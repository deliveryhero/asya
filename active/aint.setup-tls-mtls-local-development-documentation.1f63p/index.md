---
title: Document TLS/mTLS deployment guidance
status: open
priority: 4
---

Documentation-only task. Asya does NOT implement mTLS itself — it's a
deployment-time concern handled by infrastructure (service mesh, MQ TLS config).

## Context

There are two communication paths in Asya with different security models:

### 1. Actor-to-Gateway (HTTP, mesh routes)

Path: `sidecar → HTTP → asya-gateway-mesh`

With dual-deployment (Phase 1), mesh routes are ClusterIP-only. mTLS is NOT
required at the application level. If needed, platform teams enable a service
mesh (Istio/Linkerd) which provides automatic mTLS with zero Asya code changes:

```yaml
metadata:
  annotations:
    sidecar.istio.io/inject: "true"
```

### 2. Actor-to-Actor (via MQ, never direct)

Path: `Actor A sidecar → MQ (publish) → MQ (consume) → Actor B sidecar`

Actors never communicate directly. Security is handled by the transport layer:

| Transport | Auth | Encryption in transit | Access control |
|-----------|------|----------------------|----------------|
| SQS | IAM (IRSA or static creds) | TLS by default (HTTPS endpoints) | IAM policy per queue (`asya-*` prefix) |
| RabbitMQ | AMQP credentials | TLS if configured on AMQP listener | Vhost/queue-level permissions |

No application-level mTLS or message signing is needed.

## Scope (Documentation Only)

- Document how to enable TLS on RabbitMQ AMQP connections (sidecar config)
- Document IAM policy examples for SQS queue-level access control
- Document service mesh integration for automatic mTLS (Istio/Linkerd)
- Document K8s NetworkPolicy examples for restricting mesh route access
- Self-signed cert generation script for local TLS testing
- Add examples to asya-quickstart deployment guide
