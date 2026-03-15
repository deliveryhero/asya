# Asya🎭 Framework Deployment

This directory contains Helm charts for deploying the 🎭 framework components.

## What is Asya Architecture?

The Asya framework uses **Crossplane Compositions** to manage AsyncActor lifecycle. It does NOT use a custom operator - instead it leverages Crossplane's composition engine.

When installed, it:
- Uses Crossplane to watch AsyncActor XRs (Composite Resources)
- Renders sidecar containers inline into actor pods via Crossplane composition steps
- Manages Deployments based on AsyncActor specs
- Configures KEDA autoscaling
- Sets up RBAC and secrets

## Contents

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

Install Crossplane and Asya compositions:

```bash
# 1. Install Crossplane
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace

# 2. Install Asya XRDs and Compositions
kubectl apply -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crossplane.yaml

# 3. Deploy actors
kubectl apply -f ../examples/asyas/simple-actor.yaml
```

Crossplane will watch for AsyncActor resources and create the necessary Deployments, sidecars (rendered inline by the composition), and KEDA configurations.

## What Gets Deployed?

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
```

## Uninstalling

```bash
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
