# Operator Integration Tests

Integration tests for the Asya🎭 operator using [envtest](https://book.kubebuilder.io/reference/envtest.html).

**Location**: `/testing/integration/operator/`

## Overview

These tests use envtest to run a real Kubernetes API server locally (without containers) and verify core operator functionality:

- ✅ **Deployment/StatefulSet creation** with correct specs
- ✅ **Sidecar injection** into actor containers
- ✅ **Transport validation** and error handling
- ✅ **ConfigMap reconciliation** for runtime scripts
- ✅ **Owner references** for garbage collection
- ✅ **Finalizer logic** during deletion
- ✅ **Status conditions** (TransportReady, WorkloadReady)

## What's NOT Tested Here

KEDA-specific functionality requires a real cluster with KEDA installed:
- ❌ ScaledObject creation (KEDA CRDs)
- ❌ KEDA trigger configuration
- ❌ Scale-to-zero behavior

**These are tested in**: `tests/gateway-vs-actors/e2e/tests/test_keda_scaling.py`

## Prerequisites

- **Go 1.24+**
- **envtest binaries** (downloaded automatically via `make setup-envtest`)

## Running Integration Tests

### Quick Start

```bash
# From testing/integration/ directory
make test-operator

# Or from operator/ directory
make test-integration
```

This will:
1. Download envtest binaries (K8s API server, etcd)
2. Start a local K8s API server
3. Run integration tests with coverage
4. Display results

### Manual Setup

```bash
# Install envtest binaries
make setup-envtest

# Run tests with less verbose output (default value: "-v")
GOTEST_OPTS="" make integration-tests

# Run specific test
KUBEBUILDER_ASSETS="$(setup-envtest use 1.29.0 -p path)" \
  go test -v -tags=integration ./tests/integration -run TestDeploymentCreation

# View coverage report
make integration-cov
```

## Test Structure

```
tests/integration/
├── suite_test.go           # envtest setup (BeforeSuite/AfterSuite)
├── asyncactor_test.go      # Main integration tests
├── testdata/               # Test fixtures (if needed)
└── README.md               # This file
```

### Test Framework

Uses [Ginkgo](https://onsi.github.io/ginkgo/) and [Gomega](https://onsi.github.io/gomega/) (standard for Kubebuilder projects):

```go
var _ = Describe("AsyncActor Controller", func() {
    It("Should create a Deployment with sidecar injected", func() {
        // Create AsyncActor
        actor := &asyav1alpha1.AsyncActor{...}
        Expect(k8sClient.Create(ctx, actor)).Should(Succeed())

        // Wait for Deployment
        deployment := &appsv1.Deployment{}
        Eventually(func() error {
            return k8sClient.Get(ctx, ..., deployment)
        }, timeout, interval).Should(Succeed())

        // Assertions
        Expect(deployment.Spec.Template.Spec.Containers).To(HaveLen(2))
    })
})
```

## Test Coverage

### Core Controller Logic

| Test | File | What It Verifies |
|------|------|------------------|
| Create Deployment-based AsyncActor | `asyncactor_test.go` | Deployment created with sidecar |
| Create StatefulSet-based AsyncActor | `asyncactor_test.go` | StatefulSet created with sidecar |
| Update AsyncActor | `asyncactor_test.go` | Workload updated when spec changes |
| Delete AsyncActor | `asyncactor_test.go` | Workload cleaned up via owner ref |
| Invalid transport | `asyncactor_test.go` | TransportReady condition = False |
| Custom replicas | `asyncactor_test.go` | Replica count set correctly |
| Custom Python executable | `asyncactor_test.go` | ASYA_PYTHON_EXECUTABLE injected |

### What Gets Tested

**AsyncActor Controller** (`internal/controller/asya_controller.go`):
- ✅ `Reconcile()` - main reconciliation loop
- ✅ `reconcileDeployment()` - Deployment creation/update
- ✅ `reconcileStatefulSet()` - StatefulSet creation/update
- ✅ `reconcileDelete()` - finalizer cleanup
- ✅ `setCondition()` - status condition management
- ✅ `buildSidecarEnv()` - sidecar environment variables

**Sidecar Injection** (`internal/controller/sidecar.go`):
- ✅ Container injection logic
- ✅ Volume mount setup
- ✅ Liveness/readiness probes

**Transport Config** (`internal/controller/transport_config.go`):
- ✅ Transport registry validation
- ✅ Invalid transport handling

## How envtest Works

```
┌──────────────────────────────────────────┐
│  Go Test Process                         │
│  ┌────────────────────────────────────┐  │
│  │ BeforeSuite                        │  │
│  │ - Start etcd                       │  │
│  │ - Start kube-apiserver             │  │
│  │ - Install AsyncActor CRDs          │  │
│  │ - Start operator controller        │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ Tests                              │  │
│  │ - Create AsyncActor CRs            │  │
│  │ - Verify Deployments/StatefulSets  │  │
│  │ - Test updates/deletes             │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ AfterSuite                         │  │
│  │ - Stop controller                  │  │
│  │ - Stop kube-apiserver              │  │
│  │ - Cleanup                          │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

**Key Points**:
- Real K8s API server (not mocked)
- No Docker/containers required
- Fast (seconds, not minutes)
- Perfect for controller logic
- Cannot test KEDA (no KEDA CRDs/controllers)

## Debugging

### Enable Verbose Logging

```bash
# Show Ginkgo progress
go test -v -tags=integration ./tests/integration/...

# Show controller logs
# Edit suite_test.go to set log level
logf.SetLogger(zap.New(zap.WriteTo(GinkgoWriter), zap.UseDevMode(true)))
```

### Common Issues

**Test hangs during BeforeSuite**:
- Check if envtest binaries are downloaded: `ls ~/.local/share/kubebuilder-envtest/`
- Re-run setup: `make setup-envtest`

**CRD not found errors**:
- Verify CRD path in `suite_test.go`: `config/crd`
- Regenerate CRDs: `cd ../.. && make manifests`

**Controller panics**:
- Check transport registry setup in `suite_test.go`
- Verify scheme has AsyncActor types registered

## CI Integration

Integration tests run in CI:

```yaml
# .github/workflows/operator-tests.yml
- name: Run Integration Tests
  run: |
    cd operator
    make integration-tests
    make integration-cov
```

## Adding New Tests

1. Add test case to `asyncactor_test.go` (or create new file)
2. Use Ginkgo `Describe/Context/It` structure
3. Follow pattern: Create → Wait → Verify → Cleanup

Example:

```go
It("Should do something new", func() {
    actor := &asyav1alpha1.AsyncActor{
        ObjectMeta: metav1.ObjectMeta{
            Name:      "test-new-feature",
            Namespace: "test-system",
        },
        Spec: asyav1alpha1.AsyncActorSpec{
            // Your spec
        },
    }

    Expect(k8sClient.Create(ctx, actor)).Should(Succeed())

    // Wait for resource
    Eventually(func() error {
        return k8sClient.Get(ctx, ...)
    }, timeout, interval).Should(Succeed())

    // Assertions
    Expect(...).To(Equal(...))

    // Cleanup
    Expect(k8sClient.Delete(ctx, actor)).Should(Succeed())
})
```

## Performance

Typical test run:
- **Setup**: 2-3 seconds (start API server)
- **Per test**: 0.1-0.5 seconds
- **Total**: ~10-15 seconds for full suite

Much faster than Kind-based e2e tests (~2-3 minutes).

## Related Documentation

- [envtest Documentation](https://book.kubebuilder.io/reference/envtest.html)
- [Ginkgo Testing Framework](https://onsi.github.io/ginkgo/)
- [KEDA E2E Tests](../../../tests/gateway-vs-actors/e2e/tests/README_KEDA.md)
- [Operator Unit Tests](../../internal/controller/)
