# Getting Started with Asya Playground Chart

One-command quickstart using the `asya-playground` umbrella Helm chart.
This chart bundles KEDA, Crossplane providers, crew actors,
and sample infrastructure (LocalStack for SQS/S3) into a single Helm release.

## What You'll Deploy

- **KEDA** for autoscaling actors based on SQS queue depth
- **Crossplane providers** + XRDs + Compositions for AsyncActor lifecycle management
- **Crossplane compositions** with inline sidecar rendering
- **Crew actors** (x-sink, x-sump) for pipeline completion
- **LocalStack** for SQS and S3 emulation
- **Hello-world actor** to verify the installation

## Prerequisites

- [Docker](https://www.docker.com/get-started/) 24+
- [kubectl](https://kubernetes.io/docs/tasks/tools/) 1.28+
- [Helm](https://helm.sh/docs/intro/install/) 3.12+
- [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) 0.20+
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) (for sending test messages)

## 1. Create Kind Cluster

```bash
kind create cluster --name asya-playground --wait 60s
```

## 2. Install Cluster Prerequisites

The playground chart requires Crossplane to be installed first:

```bash
# Crossplane (for provider-based infrastructure management)
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace --wait --timeout 120s
```

## 3. Build and Load Images

From the repository root:

```bash
# Build all component images
make build-images

# Load into Kind
kind load docker-image \
  ghcr.io/deliveryhero/asya-sidecar:latest \
  ghcr.io/deliveryhero/asya-crew:latest \
  ghcr.io/deliveryhero/asya-gateway:latest \
  --name asya-playground
```

## 4. Create Crossplane Credentials

Crossplane AWS providers need credentials in INI format:

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: aws-creds
  namespace: crossplane-system
type: Opaque
stringData:
  credentials: |
    [default]
    aws_access_key_id = test
    aws_secret_access_key = test
EOF
```

## 5. Prepare the Chart

```bash
cd deploy/helm-charts/asya-playground
cp Chart.yaml.local Chart.yaml
helm dependency build .
```

## 6. Install (Three-Step Process)

The installation requires three steps because Crossplane providers must register
their CRDs before AsyncActor resources (crew, hello actor) can be created.

### Step 1: Install infrastructure (no actors)

```bash
helm install asya . -n asya-demo --create-namespace \
  --set asya-crossplane.providerConfigs.install=false \
  --set asya-crossplane.actorNamespace=asya-demo \
  --set asya-crossplane.awsProviderConfig.endpoint.url=http://localstack-sqs.asya-demo:4566 \
  --set enableAsyaCrew=false \
  --set enableAsyaGateway=false \
  --set sampleMonitoring.enabled=false \
  --set sampleGatewayDb.postgresql.enabled=false \
  --set helloActor.enabled=false \
  --timeout 600s --wait
```

### Step 2: Wait for providers, enable ProviderConfigs

```bash
# Wait for all Crossplane providers to become healthy
echo "Waiting for providers..."
until kubectl get providers,functions \
  -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Healthy")].status}{" "}{end}' 2>/dev/null \
  | grep -q "True True True True"; do
  sleep 5
done
echo "All providers healthy"

# Enable ProviderConfigs (now that CRDs exist)
helm upgrade asya . -n asya-demo \
  --reuse-values \
  --set asya-crossplane.providerConfigs.install=true \
  --timeout 120s --wait
```

### Step 3: Verify XRD, then enable actors

```bash
# Verify the AsyncActor XRD is established
kubectl get xrd xasyncactors.asya.sh
# Should show: ESTABLISHED=True, OFFERED=True

# Enable crew actors and hello actor
helm upgrade asya . -n asya-demo \
  --reuse-values \
  --set enableAsyaCrew=true \
  --set helloActor.enabled=true \
  --set asya-crew.image.tag=latest \
  --set asya-crew.image.pullPolicy=Never \
  --set asya-crew.x-sink.sidecar.image=ghcr.io/deliveryhero/asya-sidecar:latest \
  --set asya-crew.x-sink.sidecar.imagePullPolicy=Never \
  --set asya-crew.x-sump.sidecar.image=ghcr.io/deliveryhero/asya-sidecar:latest \
  --set asya-crew.x-sump.sidecar.imagePullPolicy=Never \
  --timeout 300s --wait
```

## 7. Verify Installation

```bash
# Check all pods are running
kubectl get pods -n asya-demo

# Expected output:
# crossplane-...           1/1     Running
# x-sump-...               2/2     Running
# x-sink-...               2/2     Running
# hello-...                 0/0    (scaled to zero by KEDA)
# keda-operator-...        1/1     Running
# localstack-sqs-...       1/1     Running
# s3-localstack-...        1/1     Running

# Check AsyncActors
kubectl get asyncactors -n asya-demo

# Expected:
# hello       Napping    (scaled to 0, waiting for messages)
# x-sink      Creating   (running with minReplicaCount=1)
# x-sump      Creating   (running with minReplicaCount=1)

# Check SQS queues were created
kubectl get queue.sqs.aws.upbound.io
# Should show 3 queues: hello, x-sink, x-sump

# Check KEDA ScaledObjects
kubectl get scaledobject -n asya-demo
# All should show READY=True
```

## 8. Test: Send a Message

Send a test message to trigger the hello actor to scale from zero:

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli -n asya-demo \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack-sqs.asya-demo:4566 \
      --queue-url http://localstack-sqs.asya-demo:4566/000000000000/asya-asya-demo-hello \
      --message-body '{\"id\":\"test-1\",\"route\":{\"actors\":[\"hello\"],\"current\":0},\"headers\":{},\"payload\":{\"name\":\"Playground\"}}'
  "
```

## 9. Watch Scale-from-Zero

```bash
# Watch the hello deployment scale up (takes ~30s for KEDA to detect the message)
kubectl get deployment hello -n asya-demo -w

# Once the pod appears, check it has 2 containers (runtime + sidecar rendered inline)
kubectl get pods -n asya-demo -l asya.sh/actor=hello
# Should show: 2/2 Running
```

## 10. Check Logs

```bash
# Sidecar logs (message routing)
POD=$(kubectl get pods -n asya-demo -l asya.sh/actor=hello -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n asya-demo $POD -c asya-sidecar --tail=10
# Should show: "Runtime call completed" and "SQS message sent successfully"

# Runtime logs (handler execution)
kubectl logs -n asya-demo $POD -c asya-runtime --tail=10
# Should show: user_func returned: {'greeting': 'Hello, Playground!', ...}
```

After the KEDA cooldown period (default 300s), the hello actor scales back to zero.

## 11. Clean Up

```bash
helm uninstall asya -n asya-demo
kind delete cluster --name asya-playground
```

Don't forget to restore Chart.yaml:

```bash
git checkout deploy/helm-charts/asya-playground/Chart.yaml
```

## Troubleshooting

### AsyncActor CRD not found

If you see `no matches for kind "AsyncActor"`, the Crossplane providers haven't
finished installing their CRDs yet. Wait for providers to be healthy:

```bash
kubectl get providers,functions
# All should show Healthy=True
```

### Crew pods in ErrImageNeverPull

The crew chart defaults to `Chart.AppVersion` for the image tag. Set explicitly:

```bash
--set asya-crew.image.tag=latest
```

### Sidecar crashes with gateway health check failure

If the gateway is not installed, clear the gateway URL in the asya-crossplane chart values:

```bash
--set asya-crossplane.sidecar.gatewayURL=""
```

Then delete affected pods to trigger reconciliation:

```bash
kubectl delete pods -n asya-demo -l asya.sh/actor
```

### Pods show 1/2 containers

The Crossplane composition may not have finished reconciling. Check the AsyncActor status:

```bash
kubectl get asyncactor -n asya-demo
kubectl describe asyncactor hello -n asya-demo
```

## What's Next?

- **Enable Gateway**: Add `--set enableAsyaGateway=true` for HTTP API and MCP tools
- **Enable Monitoring**: Add `--set sampleMonitoring.enabled=true` for Prometheus + Grafana
- **Add custom actors**: Create your own AsyncActor resources following the hello-actor pattern
- **Production deployment**: See [AWS EKS Installation](../install/aws-eks.md)
- **Flow DSL**: Write pipelines in Python-like syntax with `asya flow compile`
