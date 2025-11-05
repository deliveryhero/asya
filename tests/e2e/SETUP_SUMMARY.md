# Asya Kind Deployment - Setup Summary

## What Was Created

A complete local deployment solution for the Asya framework using Kind (Kubernetes in Docker).

### Directory Structure

```
examples/deployment-kind/
├── README.md                    # Comprehensive documentation
├── QUICKSTART.md                # Quick start guide
├── SETUP_SUMMARY.md            # This file
├── kind-config.yaml            # Kind cluster configuration
├── values.yaml                 # Shared deployment values
├── example-actor.yaml          # Example Asya actor CRD
├── rabbitmq-secret.yaml        # RabbitMQ credentials secret
└── scripts/
    ├── deploy.sh               # Main deployment script
    ├── cleanup.sh              # Cleanup script
    └── test-e2e.sh                 # Deployment verification script
```

## Scripts

### `deploy.sh`

**Purpose**: Automated deployment of the complete Asya stack to Kind.

**What it does**:
1. Checks prerequisites (kind, kubectl, helm, docker)
2. Creates Kind cluster with 1 control-plane + 2 workers
3. Loads Docker images (asya-operator, asya-gateway, asya-sidecar, asya-runtime)
4. Adds Helm repositories (bitnami, kedacore)
5. Creates namespaces (asya, asya-system, keda)
6. Installs RabbitMQ (message queue)
7. Installs PostgreSQL (database)
8. Installs KEDA (autoscaling)
9. Installs AsyncActor CRDs
10. Installs Asya Operator
11. Installs Asya Gateway
12. Verifies deployment
13. Prints access information

**Usage**:
```bash
./scripts/deploy.sh
```

**Duration**: ~10-15 minutes (depending on network speed)

### `cleanup.sh`

**Purpose**: Remove Asya components or entire cluster.

**What it does**:
- Uninstalls all Helm releases
- Deletes AsyncActor CRDs
- Removes PersistentVolumeClaims
- Deletes namespaces
- Optionally deletes Kind cluster

**Usage**:
```bash
# Remove components only
./scripts/cleanup.sh

# Remove everything
./scripts/cleanup.sh --cluster
```

### `test-e2e.sh`

**Purpose**: Verify deployment health.

**What it checks**:
- Cluster accessibility
- Namespace existence
- CRD installation
- Helm release status
- Pod readiness
- Service availability

**Usage**:
```bash
./scripts/test-e2e.sh
```

## Configuration Files

### `kind-config.yaml`

Defines a 3-node Kind cluster:
- 1 control-plane node
- 2 worker nodes
- Port mappings for HTTP (8080) and HTTPS (8443)

### `values.yaml`

Shared configuration values with resource limits optimized for local deployment:
- RabbitMQ: 100m CPU / 256Mi RAM
- PostgreSQL: 100m CPU / 128Mi RAM
- KEDA: 50m CPU / 64Mi RAM
- Asya components: 50-100m CPU / 64-128Mi RAM

### `example-actor.yaml`

Sample AsyncActor CRD that demonstrates:
- RabbitMQ transport configuration
- Sidecar injection
- KEDA autoscaling (0-10 replicas)
- Socket communication
- Resource limits

### `rabbitmq-secret.yaml`

Kubernetes Secret containing RabbitMQ credentials required by the example actor.

## Deployment Components

### Infrastructure (namespace: asya)

1. **RabbitMQ**
   - Chart: bitnami/rabbitmq v12.x
   - Credentials: asya/asya-password
   - Management UI: Port 15672

2. **PostgreSQL**
   - Chart: bitnami/postgresql v13.x
   - Credentials: asya/asya-db-password
   - Database: asya

3. **KEDA**
   - Chart: kedacore/keda v2.x
   - Namespace: keda
   - Purpose: Event-driven autoscaling

### Asya Components

1. **Asya Operator** (namespace: asya-system)
   - Custom Kubernetes operator
   - Watches AsyncActor CRDs
   - Injects sidecars
   - Creates workloads

2. **Asya Gateway** (namespace: asya)
   - MCP JSON-RPC 2.0 gateway
   - Job management
   - PostgreSQL backend for job storage

## Usage Instructions

### Deploy the Stack

```bash
# From project root
cd examples/deployment-kind

# Run deployment
./scripts/deploy.sh
```

### Verify Deployment

```bash
./scripts/test-e2e.sh
```

### Deploy Example Actor

```bash
# Create RabbitMQ secret
kubectl apply -f rabbitmq-secret.yaml

# Deploy actor
kubectl apply -f example-actor.yaml

# Check status
kubectl get asya -n asya
kubectl get pods -n asya -l app=echo-actor
```

### Access Services

```bash
# RabbitMQ Management UI
kubectl port-forward -n asya svc/asya-rabbitmq 15672:15672
# Visit http://localhost:15672 (asya/asya-password)

# Asya Gateway
kubectl port-forward -n asya svc/asya-gateway 8080:80
# API available at http://localhost:8080

# PostgreSQL
kubectl port-forward -n asya svc/asya-postgresql 5432:5432
```

### Cleanup

```bash
# Remove components only (keep cluster for faster redeployment)
./scripts/cleanup.sh

# Remove everything including cluster
./scripts/cleanup.sh --cluster
```

## Key Features

### Automated Deployment
- Single command deployment
- Prerequisite checking
- Error handling and logging
- Progress indicators

### Resource Optimized
- Minimal CPU/memory footprint
- Suitable for development laptops
- 2-4 GB RAM recommended

### Reproducible
- Declarative configuration
- Version-pinned charts
- Consistent naming

### Easy Cleanup
- One-command removal
- Optional cluster preservation
- No manual cleanup needed

## Troubleshooting

### Images Not Loading

```bash
# Rebuild and reload
cd ../../..
make build-images
cd examples/deployment-kind
kind load docker-image asya-operator:latest --name asya-kind
kind load docker-image asya-gateway:latest --name asya-kind
kind load docker-image asya-sidecar:latest --name asya-kind
kind load docker-image asya-runtime:latest --name asya-kind
```

### Pods Not Starting

```bash
# Check events
kubectl get events -n asya --sort-by='.lastTimestamp'

# Describe pod
kubectl describe pod <pod-name> -n asya

# Check logs
kubectl logs <pod-name> -n asya
```

### Fresh Start

```bash
./scripts/cleanup.sh --cluster
./scripts/deploy.sh
```

## Next Steps

1. **Read the Documentation**
   - [README.md](README.md) - Full documentation
   - [QUICKSTART.md](QUICKSTART.md) - Quick reference

2. **Explore Examples**
   - Deploy the example actor
   - Modify `example-actor.yaml` for your use case
   - Check other examples in `../asyas/`

3. **Build Custom Actors**
   - Create Python handler functions
   - Build Docker images with asya-runtime
   - Deploy using AsyncActor CRD

4. **Monitor and Scale**
   - Watch KEDA autoscaling
   - Monitor RabbitMQ queues
   - View actor logs

## Files Modified/Created

### New Files Created
- `examples/deployment-kind/` (entire directory)
  - Scripts: `deploy.sh`, `cleanup.sh`, `test-e2e.sh`
  - Config: `kind-config.yaml`, `values.yaml`
  - Examples: `example-actor.yaml`, `rabbitmq-secret.yaml`
  - Docs: `README.md`, `QUICKSTART.md`, `SETUP_SUMMARY.md`

### Existing Files Modified
- `operator/api/v1alpha1/zz_generated.deepcopy.go` - Fixed type mismatch in ScalingConfig

## System Requirements

- **Docker**: Running and accessible
- **Kind**: v0.20+ installed
- **kubectl**: v1.27+ installed
- **Helm**: v3.12+ installed
- **RAM**: 2-4 GB available
- **Disk**: 10 GB free space
- **OS**: Linux, macOS, or WSL2 on Windows

## Credits

Based on the Minikube deployment (`examples/deployment-minikube/`) but optimized for Kind with:
- Faster cluster creation
- Better resource management
- Cleaner configuration
- More robust scripts
- Comprehensive documentation

## Support

For issues:
1. Check [README.md](README.md) troubleshooting section
2. Review script logs
3. Check pod events and logs
4. Consult main Asya documentation
5. Open GitHub issue
