# Asya Playground Helm Chart Testing Summary

## Bead: asya-u8y
## PR: #122
## Worktree: /home/a.yushkovskiy/asya/.worktrees/asya-u8y-umbrella-helm-chart

---

## Chart Dependencies

All asya-* charts are pulled from **OCI asya.sh/charts** (NOT local):
```yaml
dependencies:
- name: keda
  version: ">=2.16.0"
  repository: "https://kedacore.github.io/charts"
- name: asya-operator
  version: ">=0.4.0"
  repository: "https://asya.sh/charts"
- name: asya-crew
  version: ">=0.4.0"
  repository: "https://asya.sh/charts"
- name: asya-gateway
  version: ">=0.4.0"
  repository: "https://asya.sh/charts"
```

---

## Phase 1: Operator + KEDA + Hello Actor (COMPLETED)

### Objective
Test basic asya-playground installation with operator, KEDA, and a simple actor using SQS (LocalStack).

### Changes Made

| File | Change |
|------|--------|
| `Chart.yaml` | Added KEDA as non-optional dependency (`>=2.16.0`) |
| `.helmignore` | Removed `charts/` from ignore (was blocking subcharts) |
| `templates/hello-actor.yaml` | Fixed labels (removed reserved prefixes), fixed scaling config (`enabled: true` + `queueLength`), added sidecar AWS credentials |
| `values.yaml` | Added `extraEnv` for operator AWS creds, enabled SQS by default |
| `asya-operator/templates/deployment.yaml` | Added `extraEnv` support |
| `asya-operator/values.yaml` | Added `extraEnv` documentation |

### Test Results

| Component | Status |
|-----------|--------|
| Kind cluster | Created |
| KEDA (3 pods) | Running |
| asya-operator | Running |
| LocalStack SQS | Running |
| Hello actor | Running |
| KEDA ScaledObject | Created (aws-sqs-queue trigger) |
| Message processing | SUCCESS: `{'greeting': 'Hello, Asya!'}` |

### Commit
- `5942baf feat(charts): Add KEDA as non-optional playground dependency`
- Pushed to `origin/asya-u8y-umbrella-helm-chart`

---

## Phase 2: S3 Storage + Crew Actors (COMPLETED)

### Objective
Enable S3 storage (LocalStack) and crew actors (happy-end, error-end) to test full pipeline completion with result persistence.

### Changes Made

| File | Change |
|------|--------|
| `asya-crew/templates/happy-end.yaml` | Added sidecar section support (`{{- with $happyEnd.sidecar }}`) |
| `asya-crew/templates/error-end.yaml` | Added sidecar section support (`{{- with $errorEnd.sidecar }}`) |
| `asya-crew/values.yaml` | Added sidecar config for both actors |
| `Chart.yaml.local` | Added KEDA dependency for local testing |

### Test Results

| Component | Status |
|-----------|--------|
| Kind cluster | Created |
| KEDA (3 pods) | Running |
| asya-operator | Running |
| LocalStack SQS | Running |
| LocalStack S3 | Running |
| Hello actor | Running |
| Happy-end actor | Running |
| Error-end actor | Running |
| Full pipeline | SUCCESS |
| S3 persistence | SUCCESS |

### Pipeline Flow
```
hello → happy-end → S3
```

### Verification
```
Message sent: phase2-s3-test
Hello output: {'greeting': 'Hello, S3 Storage Test!', 'message': 'Welcome to Asya Actor Mesh'}
Happy-end output: S3 persisted: True
S3 key: s3://asya-results/happy-asya/2026-02-03T13:04:47.172414Z/hello/phase2-s3-test.json
```

### Key Configuration
```yaml
asya-crew:
  happy-end:
    transport: sqs
    env:
      ASYA_S3_BUCKET: "asya-results"
      ASYA_S3_ENDPOINT: "http://s3-localstack:4566"
      ASYA_S3_REGION: "us-east-1"
      ASYA_S3_ACCESS_KEY: "test"
      ASYA_S3_SECRET_KEY: "test"
    sidecar:
      env:
      - name: AWS_ACCESS_KEY_ID
        value: "test"
      - name: AWS_SECRET_ACCESS_KEY
        value: "test"
      - name: AWS_REGION
        value: "us-east-1"
```

---

### Commits
- `9ac1155` - Add sidecar support to asya-crew chart
- `7da0129` - Regenerate Chart.lock with remote dependencies

---

## Phase 3: Prometheus + Grafana Stack (COMPLETED ✅)

### Objective
Add kube-prometheus-stack as a sample dependency to asya-playground for optional observability.

### Changes Made

| File | Change |
|------|--------|
| `Chart.yaml` | Added kube-prometheus-stack dependency with `condition: sampleMonitoring.enabled` |
| `Chart.yaml.local` | Same dependency added |
| `values.yaml` | Added `sampleMonitoring.enabled: false` and kube-prometheus-stack config |
| `templates/sample-monitoring/prometheus-grafana/dashboard-configmap.yaml` | ConfigMap loading dashboard via symlink |
| `templates/sample-monitoring/prometheus-grafana/podmonitor.yaml` | PodMonitor for actor metrics (matches `asya.sh/actor` label) |
| `files/asya-actors-overview.json` | Symlink to `deploy/grafana-dashboards/asya-actors-overview.json` |
| `.pre-commit-hooks/check-chart-locks.sh` | New hook to prevent file:// in Chart.lock |
| `.pre-commit-hooks/check-symlinks.sh` | Added dashboard symlink mapping |

### Test Results

| Component | Status |
|-----------|--------|
| Kind cluster | ✅ Created (asya-playground-phase3) |
| kube-prometheus-stack | ✅ Deployed (Prometheus + Grafana) |
| Prometheus StatefulSet | ✅ Running (1/1) |
| Grafana | ✅ Running (1/1) |
| KEDA | ✅ Running (3 pods) |
| asya-operator | ✅ Running |
| Hello actor | ✅ Running (2/2 containers) |
| PodMonitor | ✅ Created (matches `asya.sh/actor` labels) |
| Grafana Dashboard ConfigMap | ✅ Created |
| Message processing | ✅ SUCCESS |
| Metrics collection | ✅ **FIXED** - operator enhanced with metrics port |
| Prometheus scraping | ✅ All 6 actor pods scraped (job: asya-demo/asya-actors) |
| Grafana dashboard | ✅ Metrics visible and rendering |

### Issue Found & Fixed ✅

**Problem**: Metrics not being scraped by Prometheus

**Root Cause**: Sidecar container missing `ports` definition in deployment spec

**Impact**: PodMonitor couldn't discover metrics endpoint without named port

**Fix Applied**: Added named `metrics` port (8080/TCP) to sidecar container in operator

**File Changed**: `src/asya-operator/internal/controller/asya_controller.go`

**Verification**:
- ✅ All 6 actor pods scraped by Prometheus (job: `asya-demo/asya-actors`)
- ✅ 19 distinct asya_actor_* metrics available
- ✅ Metrics flowing: messages_received_total (263 total), active_messages, processing_duration_seconds
- ✅ Grafana dashboard displaying metrics (user confirmed)
- ✅ Unit tests passing (coverage: 62.2%)

**Solution**: PodMonitor pattern with named port - simpler than ServiceMonitor, matches existing `asya.sh/actor` labels

**Available Metrics**:
```
asya_actor_active_messages
asya_actor_messages_received_total
asya_actor_messages_sent_total
asya_actor_messages_processed_total
asya_actor_messages_failed_total
asya_actor_processing_duration_seconds (histogram)
asya_actor_runtime_execution_duration_seconds (histogram)
asya_actor_queue_receive_duration_seconds (histogram)
asya_actor_queue_send_duration_seconds (histogram)
asya_actor_envelope_size_bytes (histogram)
```

### Cluster State
**Status**: Active - `kind-asya-playground-phase3`

**Access Points**:
```bash
# Grafana (default: admin/prom-operator)
kubectl port-forward -n asya-demo svc/asya-grafana 3000:80
# Browser: http://localhost:3000

# Prometheus
kubectl port-forward -n asya-demo svc/asya-kube-prometheus-stack-prometheus 9090:9090
# Browser: http://localhost:9090
```

**Metrics Query Examples**:
```promql
# Active messages per actor
asya_actor_active_messages

# Message processing rate (per second)
rate(asya_actor_messages_received_total[1m])

# P95 processing duration
histogram_quantile(0.95, rate(asya_actor_processing_duration_seconds_bucket[5m]))

# Total messages by actor
sum by (asya_actor_name) (asya_actor_messages_received_total)
```

---

## Phase 3C: k6 Load Testing (COMPLETED)

### Objective
Replace Locust with k6 (CNCF-native) using standard grafana/k6 image and jslib AWS.

### Implementation

| Component | Status |
|-----------|--------|
| k6-scripts-configmap.yaml | ✅ Created |
| k6-sqs-job.yaml | ✅ Created |
| values.yaml k6LoadTests | ✅ Added |
| Standard grafana/k6 image | ✅ Used (no custom builds) |
| jslib AWS from CDN | ✅ Working |

### Test Results

| Component | Status |
|-----------|--------|
| k6 Job deployed | ✅ Running |
| SQS messaging | ✅ Working (460+ messages in 24s) |
| LocalStack integration | ✅ Working (custom endpoint) |
| Chaos actors | ✅ Processing messages |
| No custom builds | ✅ Confirmed |
| No CI changes | ✅ Confirmed |

### Key Features
- Uses standard `grafana/k6:0.54.0` image
- jslib AWS 0.12.3 loaded from CDN
- AWSConfig.endpoint for LocalStack
- 20 VUs, 5m duration
- Random actor selection (chaos-slow, chaos-flaky, chaos-cpu, chaos-fanout)

---

## Phase 3 Summary

### All Commits (Phases 3A-3C)
- `5942baf` - Phase 3A: Add KEDA as non-optional playground dependency
- `9ac1155` - Phase 3A: Add sidecar support to asya-crew chart
- `7da0129` - Phase 3A: Regenerate Chart.lock with remote dependencies
- `448811c` - Phase 3C: Initial k6 implementation
- `bd768c2` - Phase 3C: Fix AWS credential length requirements
- `adb0082` - Phase 3C: Working simplified script
- `47d4cd9` - **Phase 3: Add metrics port to sidecar for Prometheus discovery** ✅

### Phase 3 Achievements
✅ **Monitoring Stack**: kube-prometheus-stack deployed and configured
✅ **Metrics Collection**: PodMonitor auto-discovering actor metrics
✅ **Grafana Dashboard**: Asya Actors Overview dashboard loaded and working
✅ **Load Testing**: K6 integration with LocalStack SQS
✅ **Operator Enhancement**: Metrics port added to all future AsyncActors
✅ **Full Observability**: 19 metrics types across 6 actor pods

### Technical Highlights
- **Zero-config metrics**: All AsyncActors automatically expose metrics on port 8080
- **PodMonitor discovery**: Label-based scraping without Service objects
- **Histogram metrics**: Detailed latency distributions for processing, queue ops, runtime execution
- **CNCF tooling**: Standard Prometheus + Grafana + K6 stack

---

## Phase 4: Gateway + PostgreSQL + Namespace Separation (COMPLETED ✅)

### Objective
Enable MCP gateway with PostgreSQL for envelope tracking and HTTP API. Add namespace separation for infrastructure components.

### Changes Made

| File | Change |
|------|--------|
| `values.yaml` | Added `namespaces.monitoring` and `namespaces.infra` config |
| `templates/_helpers.tpl` | Added namespace helper functions + Prometheus URL helper |
| `templates/sample-gateway-db/postgresql/*.yaml` | Updated to use infra namespace + release name prefix + pre-install hooks |
| `templates/sample-transport/sqs-localstack/*.yaml` | Updated to use infra namespace |
| `templates/sample-transport/rabbitmq/*.yaml` | Updated to use infra namespace |
| `templates/sample-storage/s3-localstack/*.yaml` | Updated to use infra namespace |
| `templates/sample-storage/minio/*.yaml` | Updated to use infra namespace |
| `templates/sample-monitoring/prometheus-grafana/*.yaml` | Updated to use monitoring namespace |
| `templates/testing-actors/k6-sqs-job.yaml` | Dynamic Prometheus URL based on namespace |

### Test Results

| Component | Status |
|-----------|--------|
| Kind cluster | ✅ Created (asya-playground-phase4) |
| PostgreSQL StatefulSet | ✅ Running (with pre-install hooks) |
| DB Migration Job | ✅ Completed |
| asya-gateway | ✅ Running (connected to PostgreSQL) |
| KEDA | ✅ Running (3 pods) |
| asya-operator | ✅ Running |
| LocalStack SQS | ✅ Running |
| LocalStack S3 | ✅ Running |
| Prometheus | ✅ Running |
| Grafana | ✅ Running |
| Crew actors (happy-end, error-end) | ✅ Running |
| Chaos actors | ✅ Running |
| Hello actor | ✅ Running |
| k6 load test | ✅ Completed |
| Metrics collection | ✅ All 15+ pods scraped |
| Grafana dashboard | ✅ Rendering metrics |

### Namespace Separation Feature

**Usage:**
```bash
kubectl create namespace monitoring
kubectl create namespace asya-infra
helm install asya . -n asya-demo --create-namespace \
  --set namespaces.monitoring=monitoring \
  --set namespaces.infra=asya-infra \
  --set kube-prometheus-stack.namespaceOverride=monitoring
```

**Namespace Distribution:**
| Namespace | Components |
|-----------|------------|
| `asya-demo` (release) | Operator, Gateway, Crew, Actors, KEDA |
| `monitoring` | Dashboard ConfigMap, PodMonitor, Prometheus*, Grafana* |
| `asya-infra` | LocalStack SQS/S3, MinIO, PostgreSQL |

*Requires additional `kube-prometheus-stack.namespaceOverride=monitoring`

### Issues Found & Fixed

**Issue 1: PostgreSQL naming mismatch**
- **Problem**: Gateway expected secret `{release}-asya-gateway-postgresql` but template created `asya-gateway-postgresql`
- **Fix**: Added `{{ .Release.Name }}-` prefix to all PostgreSQL resources

**Issue 2: PostgreSQL created after migration job**
- **Problem**: Migration job (pre-install hook weight -5) ran before PostgreSQL was ready
- **Fix**: Added pre-install hooks with weight -15 to PostgreSQL resources

**Issue 3: Password mismatch**
- **Problem**: Gateway chart creates its own secret with different password
- **Fix**: Aligned passwords between gateway and PostgreSQL configuration

**Issue 4: Metrics not being scraped (from Phase 3)**
- **Problem**: Published operator image didn't include metrics port on sidecar
- **Fix**: Built local operator/sidecar images with metrics port and loaded to Kind

### Verification Commands
```bash
# Check all components
kubectl get pods -n asya-demo

# Verify metrics in Prometheus
curl -s "http://localhost:9090/api/v1/query?query=asya_actor_messages_processed_total"

# Access Grafana dashboard
# URL: http://localhost:3000/d/asya-actors-v3/asya-actors-overview
# Credentials: admin / asya-admin
```

### Commits
- `24a86ae` - feat(playground): Add namespace separation for monitoring and infra

---

## Phase 5: Full Integration Testing (TODO)

### Objective
Test complete asya-playground with all components + autoscaling.

### Components
- All previous phases working together
- KEDA autoscaling validation (scale up/down/zero)
- Multi-actor pipeline testing
- Error handling and DLQ verification
- Performance testing under load

### Success Criteria
- ✅ Scale to zero working (no messages = 0 replicas)
- ✅ Scale up on load (messages arrive = replicas increase)
- ✅ Multi-actor pipelines complete end-to-end
- ✅ Error-end and DLQ handling working
- ✅ Grafana shows accurate metrics during scaling events

---

## Quick Reference

### Create test cluster
```bash
kind create cluster --name asya-playground
kubectl apply -f src/asya-operator/config/crd/asya.sh_asyncactors.yaml
```

### Install playground
```bash
cd deploy/helm-charts/asya-playground
helm dependency build .
helm install asya . -n asya-demo --create-namespace --dependency-update
```

### Send test message
```bash
MSG='{"id":"test-1","route":{"actors":["hello"],"current":0},"payload":{"name":"Asya"}}'
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-demo \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack-sqs.asya-demo:4566 \
      --queue-url http://localstack-sqs.asya-demo:4566/000000000000/asya-asya-demo-hello \
      --message-body '\$MSG'
  "
```

### Check logs
```bash
kubectl logs -l asya.sh/actor=hello -c asya-runtime -n asya-demo
kubectl logs -l asya.sh/actor=hello -c asya-sidecar -n asya-demo
```

### Cleanup
```bash
helm uninstall asya -n asya-demo
kind delete cluster --name asya-playground
```




----
❯ how to trigger k6?

● The k6 Job is already running! It will complete automatically after 5 minutes. To check status or trigger manually:

Check Current Job:
# Watch progress
kubectl logs -n asya-demo -l test-type=sqs -f

# Check job status
kubectl get jobs -n asya-demo

Trigger New Test (after current one finishes):
# Delete completed job
kubectl delete job k6-load-test-sqs -n asya-demo

# Trigger new test via Helm
helm upgrade asya . -n asya-demo \
--values /tmp/asya-playground-test/phase3c/values-phase3c.yaml \
--set k6LoadTests.sqs.enabled=true

# Or create job directly
kubectl create job k6-load-test-sqs-manual \
--from=job/k6-load-test-sqs -n asya-demo

Quick Manual Trigger:
kubectl delete job k6-load-test-sqs -n asya-demo
kubectl apply -f /home/a.yushkovskiy/asya/.worktrees/asya-u8y-umbrella-helm-chart/deploy/helm-charts/asya-playground/templates/testing-actors/k6-sqs-job.yaml

The Job runs once and exits. For continuous testing, you'd change it to a CronJob or keep re-triggering manually.



----
  Quick Access

  # View metrics in Grafana (admin/prom-operator)
  kubectl port-forward -n asya-demo svc/asya-grafana 3000:80

  # Query metrics directly in Prometheus
  kubectl port-forward -n asya-demo svc/asya-kube-prometheus-stack-prometheus 9090:9090

  # Trigger new load test
  kubectl create job k6-load-test-sqs --from-job/k6-load-test-sqs -n asya-demo
