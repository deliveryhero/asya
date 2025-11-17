# Installation

## Prerequisites

- Kubernetes 1.23+
- kubectl (configured)
- Helm 3.0+
- (Optional) KEDA 2.0+ for autoscaling

## Quick Start (Recommended)

Automated deployment with Kind (~5-10 minutes):

```bash
cd tests/gateway-vs-actors/e2e
./scripts/deploy.sh      # Complete stack with infrastructure
./scripts/test-e2e.sh    # Verify deployment
```

Services available at:
- Gateway (MCP): http://localhost:8080
- Grafana: http://localhost:3000 (admin/admin)

## Manual Installation

### Step 1: Install CRDs

```bash
kubectl apply -f src/asya-operator/config/crd/
kubectl get crd asyncactors.asya.sh  # Verify
```

### Step 2: Install Operator

```bash
helm install asya-operator deploy/helm-charts/asya-operator \
  -n asya-system --create-namespace

kubectl get pods -n asya-system  # Verify
```

### Step 3: Install Gateway (Optional)

```bash
helm install asya-gateway deploy/helm-charts/asya-gateway \
  -n asya --create-namespace \
  --set postgresql.enabled=true
```

### Step 4: Install KEDA (Optional)

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda -n keda --create-namespace
```

## Verification

Deploy test actor:

```bash
kubectl apply -f examples/asyas/simple-actor.yaml
kubectl get asyas
kubectl get deployment simple-actor
```

## Troubleshooting

See [operator/README.md](../../operator/README.md#troubleshooting) for:
- CRD not found
- Operator not starting
- Actor deployment issues
- KEDA scaling problems

## Next Steps

- [Core Concepts](02-concepts.md) - Understanding Asya🎭
- [Deploy Your First Actor](quickstart.md#deploy-your-first-actor)
- [Component Documentation](../architecture/asya-gateway.md)
