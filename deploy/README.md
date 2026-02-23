# Asya🎭 Framework Deployment

This directory contains Helm charts for deploying the 🎭 framework components.

## What is Asya Architecture?

The Asya framework uses **Crossplane Compositions** to manage AsyncActor lifecycle. It does NOT use a custom operator - instead it leverages Crossplane's composition engine.

When installed, it:
- Uses Crossplane to watch AsyncActor XRs (Composite Resources)
- Automatically injects sidecar containers via asya-injector webhook
- Manages Deployments based on AsyncActor specs
- Configures KEDA autoscaling
- Sets up RBAC and secrets

## Contents

### Injector Webhook Chart (`helm-charts/asya-injector/`)

Helm chart that deploys the asya-injector webhook:

```bash
# Install the injector webhook
helm install asya-injector helm-charts/asya-injector --create-namespace -n asya-system

# Or upgrade
helm upgrade --install asya-injector helm-charts/asya-injector -n asya-system
```

### Gateway Chart (`helm-charts/asya-gateway/`)

Helm chart for deploying the 🎭 MCP gateway with PostgreSQL backend:

```bash
# Install with bundled PostgreSQL (recommended)
helm dependency update helm-charts/asya-gateway
helm install asya-gateway helm-charts/asya-gateway --create-namespace -n asya

# Or upgrade
helm upgrade --install asya-gateway helm-charts/asya-gateway -n asya
```

See [helm-charts/asya-gateway/README.md](helm-charts/asya-gateway/README.md) for detailed configuration options.

## Quick Start

**Automated E2E Testing Deployment**

For local testing with full stack:
```bash
cd ../testing/e2e
make up
```

See [docs/install/local-kind.md](../docs/install/local-kind.md) for detailed local deployment instructions.

**Minimal Framework Installation**

Install Crossplane, Asya compositions, and injector webhook:

```bash
# 1. Install Crossplane
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace

# 2. Install Asya XRDs and Compositions
kubectl apply -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crossplane.yaml

# 3. Install asya-injector webhook
helm install asya-injector helm-charts/asya-injector --create-namespace -n asya-system

# 4. Deploy actors
kubectl apply -f ../examples/asyas/simple-actor.yaml
```

Crossplane will watch for AsyncActor resources and create the necessary Deployments, sidecars, and KEDA configurations.

## What Gets Deployed?

**The injector chart deploys:**
- 1 injector webhook Deployment (runs the `asya-injector` pod)
- ServiceAccount and RBAC for the injector
- MutatingWebhookConfiguration for sidecar injection
- Service for webhook endpoints

**This does NOT deploy:**
- Crossplane (install separately)
- XRDs and Compositions (install separately from releases)
- Actors (create AsyncActor resources after Crossplane is running)
- KEDA (install separately if using autoscaling)

## XRD Management

AsyncActor XRDs and Compositions are maintained in Crossplane configuration packages and distributed via GitHub releases.

## Upgrading

```bash
# Update Crossplane first
helm upgrade crossplane crossplane-stable/crossplane -n crossplane-system

# Update XRDs and Compositions
kubectl apply -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crossplane.yaml

# Then upgrade injector
helm upgrade asya-injector helm-charts/asya-injector -n asya-system
```

## Uninstalling

```bash
# Delete injector
helm uninstall asya-injector -n asya-system

# Delete XRDs (WARNING: this will delete all AsyncActor resources!)
kubectl delete -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crossplane.yaml

# Uninstall Crossplane
helm uninstall crossplane -n crossplane-system
```

## Examples

See `../examples/asyas/` for AsyncActor CRD examples.

For deployment guides, see:
- [Local Kind Installation](../docs/install/local-kind.md)
- [AWS EKS Installation](../docs/install/aws-eks.md)
- [Helm Charts Documentation](../docs/install/helm-charts.md)
