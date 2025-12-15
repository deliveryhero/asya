# Upgrades

Version upgrade procedures for Asya🎭 components.

## Overview

Asya🎭 is alpha software. APIs may change between versions.

## Version Compatibility

**CRD compatibility**: Regenerate CRDs after operator upgrades
**Backward compatibility**: Not guaranteed in alpha

## Upgrade Procedure

### 1. Backup CRDs

```bash
kubectl get asyas -A -o yaml > asyas-backup.yaml
```

### 2. Upgrade CRDs

```bash
kubectl apply -f src/asya-operator/config/crd/
```

### 3. Upgrade Operator

```bash
helm upgrade asya-operator deploy/helm-charts/asya-operator/ \
  -n asya-system \
  -f operator-values.yaml
```

### 4. Upgrade Gateway

```bash
helm upgrade asya-gateway deploy/helm-charts/asya-gateway/ \
  -f gateway-values.yaml
```

### 5. Upgrade Crew

```bash
helm upgrade asya-crew deploy/helm-charts/asya-crew/ \
  -f crew-values.yaml
```

### 6. Verify

```bash
kubectl get pods -n asya-system
kubectl get asyas -A
```

## Rollback

```bash
helm rollback asya-operator -n asya-system
kubectl apply -f asyas-backup.yaml
```

## Breaking Changes

Check CHANGELOG.md for breaking changes between versions.

**Alpha notice**: Expect breaking changes. Test upgrades in staging first.
