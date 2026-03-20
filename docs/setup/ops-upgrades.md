# Upgrades

Version upgrade procedures for Asya🎭 components.

## Overview

Asya🎭 is alpha software. APIs may change between versions.

## Version Compatibility

**XRD compatibility**: Crossplane XRDs managed via asya-crossplane chart
**Backward compatibility**: Not guaranteed in alpha

## Upgrade Procedure

### 1. Backup AsyncActors

```bash
kubectl get asyncactors -A -o yaml > asyncactors-backup.yaml
```

### 2. Upgrade Crossplane Chart

```bash
helm upgrade asya-crossplane deploy/helm-charts/asya-crossplane/ \
  -n crossplane-system \
  -f crossplane-values.yaml
```

### 3. Upgrade Gateway

```bash
helm upgrade asya-gateway deploy/helm-charts/asya-gateway/ \
  -f gateway-values.yaml
```

### 4. Upgrade Crew

```bash
helm upgrade asya-crew deploy/helm-charts/asya-crew/ \
  -f crew-values.yaml
```

### 5. Verify

```bash
kubectl get pods -n crossplane-system
kubectl get pods -n asya-system
kubectl get asyncactors -A
```

## Rollback

```bash
helm rollback asya-crossplane -n crossplane-system
kubectl apply -f asyncactors-backup.yaml
```

## Breaking Changes

Check CHANGELOG.md for breaking changes between versions.

**Alpha notice**: Expect breaking changes. Test upgrades in staging first.
