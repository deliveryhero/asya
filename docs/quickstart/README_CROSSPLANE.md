# Getting Started with Asya (Crossplane Architecture)

This quickstart deploys Asya using **Crossplane Compositions** for infrastructure management
and the **asya-injector webhook** for sidecar injection, replacing the monolithic asya-operator.

## What You'll Learn

- Deploy Crossplane providers and compositions for SQS + KEDA + Kubernetes resources
- Deploy the asya-injector mutating webhook for automatic sidecar injection
- Create your first AsyncActor using a Crossplane claim
- Test autoscaling: scale-from-zero, process messages, scale-to-zero
- Delete an actor and verify all resources are cleaned up

## Prerequisites

- [Docker](https://www.docker.com/get-started/) 24+
- [kubectl](https://kubernetes.io/docs/tasks/tools/) 1.28+
- [Helm](https://helm.sh/docs/intro/install/) 3.12+
- [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) 0.20+
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) (for sending test messages)

## 1. Create Kind Cluster

```bash
kind create cluster --name asya-crossplane --wait 60s
```

## 2. Build and Load Images

From the repository root:

```bash
# Build sidecar
docker build -t asya-sidecar:latest -f src/asya-sidecar/Dockerfile src/asya-sidecar/

# Build injector
docker build -t asya-injector:latest -f src/asya-injector/Dockerfile src/asya-injector/
```

Create a test actor handler:

```bash
mkdir -p /tmp/test-actor

cat > /tmp/test-actor/handler.py <<'PYEOF'
def greet(payload):
    name = payload.get("name", "World")
    return {"greeting": f"Hello, {name}!"}
PYEOF

cat > /tmp/test-actor/Dockerfile <<'DEOF'
FROM python:3.12-slim
WORKDIR /app
COPY handler.py /app/handler.py
ENV ASYA_HANDLER=handler.greet
DEOF

docker build -t test-actor:latest /tmp/test-actor/
```

Load all images into Kind:

```bash
kind load docker-image asya-sidecar:latest asya-injector:latest test-actor:latest \
  --name asya-crossplane
```

## 3. Install Infrastructure

### cert-manager (for webhook TLS)

```bash
kubectl cluster-info --context kind-asya-crossplane
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.1/cert-manager.yaml
kubectl wait --for=condition=Available deployment/cert-manager-webhook -n cert-manager --timeout=120s
```

### Crossplane

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system --create-namespace --wait --timeout 120s
```

### KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda --namespace keda --create-namespace --wait --timeout 120s
```

### LocalStack (SQS emulator)

```bash
kubectl create namespace localstack

kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: localstack
  namespace: localstack
spec:
  replicas: 1
  selector:
    matchLabels:
      app: localstack
  template:
    metadata:
      labels:
        app: localstack
    spec:
      containers:
      - name: localstack
        image: localstack/localstack:latest
        ports:
        - containerPort: 4566
        env:
        - name: SERVICES
          value: "sqs"
        - name: DEFAULT_REGION
          value: "us-east-1"
---
apiVersion: v1
kind: Service
metadata:
  name: localstack
  namespace: localstack
spec:
  selector:
    app: localstack
  ports:
  - port: 4566
    targetPort: 4566
EOF

kubectl wait --for=condition=Available deployment/localstack -n localstack --timeout=120s
```

## 4. Install Crossplane Providers

Providers must be installed first so their CRDs are available for the chart:

```bash
kubectl apply -f - <<'EOF'
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: provider-kubernetes-watches
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  deploymentTemplate:
    spec:
      template:
        spec:
          containers:
            - name: package-runtime
              args:
                - --enable-watches
---
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-aws-sqs
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  package: xpkg.upbound.io/upbound/provider-aws-sqs:v1.19.0
---
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v0.17.0
  runtimeConfigRef:
    name: provider-kubernetes-watches
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-go-templating
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  package: xpkg.upbound.io/crossplane-contrib/function-go-templating:v0.11.3
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-patch-and-transform
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: asya-crossplane
    meta.helm.sh/release-namespace: default
spec:
  package: xpkg.crossplane.io/crossplane-contrib/function-patch-and-transform:v0.8.2
EOF
```

Wait for all providers and functions to become healthy:

```bash
echo "Waiting for providers..."
until kubectl get providers,functions -o jsonpath='{range .items[*]}{.status.conditions[?(@.type=="Healthy")].status}{" "}{end}' 2>/dev/null | grep -q "True True True True"; do
  sleep 5
done
echo "All providers healthy"
```

Grant the Kubernetes provider cluster-admin permissions:

```bash
K8S_SA=$(kubectl get providers provider-kubernetes -o jsonpath='{.status.currentRevision}')
kubectl create clusterrolebinding provider-kubernetes-admin \
  --clusterrole=cluster-admin \
  --serviceaccount="crossplane-system:${K8S_SA}"
```

## 5. Create Secrets and ConfigMaps

```bash
# Crossplane AWS credentials (INI format for Upbound providers)
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

# KEDA SQS trigger credentials
kubectl create secret generic aws-creds -n default \
  --from-literal=AWS_ACCESS_KEY_ID=test \
  --from-literal=AWS_SECRET_ACCESS_KEY=test

# asya-runtime script (mounted into actor pods)
kubectl create configmap asya-runtime -n default \
  --from-file=asya_runtime.py=src/asya-runtime/asya_runtime.py

# Create happy-end and error-end queues (normally managed by crew actors)
kubectl port-forward -n localstack svc/localstack 4566:4566 &
sleep 3
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  aws --endpoint-url=http://localhost:4566 --region us-east-1 \
  sqs create-queue --queue-name asya-default-happy-end
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  aws --endpoint-url=http://localhost:4566 --region us-east-1 \
  sqs create-queue --queue-name asya-default-error-end
kill %1 2>/dev/null
```

## 6. Install Asya Crossplane Chart

```bash
helm install asya-crossplane deploy/helm-charts/asya-crossplane/ \
  -f deploy/helm-charts/asya-crossplane/values-localstack.yaml \
  --set actorNamespace=default
```

Verify the XRD is established:

```bash
kubectl get xrd xasyncactors.asya.sh
# Should show ESTABLISHED=True, OFFERED=True
```

## 7. Install Asya Injector

```bash
helm install asya-injector deploy/helm-charts/asya-injector/ \
  --namespace asya-system --create-namespace \
  --set config.sidecarImage=asya-sidecar:latest \
  --set config.sidecarImagePullPolicy=Never \
  --set config.sqsEndpoint=http://localstack.localstack.svc.cluster.local:4566 \
  --set config.awsCredsSecret=aws-creds \
  --set image.repository=asya-injector \
  --set image.tag=latest \
  --set image.pullPolicy=Never \
  --wait --timeout 180s
```

Verify the webhook is registered:

```bash
kubectl get mutatingwebhookconfigurations
# Should show asya-injector
```

## 8. Deploy Your First Actor

```bash
kubectl apply -f - <<'EOF'
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello
  namespace: default
  labels:
    asya.sh/actor: hello
spec:
  transport: sqs
  region: us-east-1
  providerConfigRef: localstack
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    pollingInterval: 10
    cooldownPeriod: 30
    queueLength: 5
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: test-actor:latest
          imagePullPolicy: Never
          env:
          - name: ASYA_HANDLER
            value: handler.greet
          - name: ASYA_HANDLER_MODE
            value: payload
          - name: PYTHONPATH
            value: /app
EOF
```

Wait for resources:

```bash
kubectl get asyncactors -n default
# STATUS should become "Ready" or "Napping"

kubectl get queue.sqs.aws.upbound.io
# SQS queue should show READY=True

kubectl get scaledobject -n default
# ScaledObject should show READY=True
```

## 9. Test Scaling

Send a message to trigger scale-from-zero:

```bash
kubectl port-forward -n localstack svc/localstack 4566:4566 &
sleep 3

AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  aws --endpoint-url=http://localhost:4566 --region us-east-1 \
  sqs send-message \
  --queue-url http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/asya-default-hello \
  --message-body '{"id":"test-1","route":{"actors":["hello"],"current":0},"headers":{},"payload":{"name":"Crossplane"}}'

kill %1 2>/dev/null
```

Watch the pod scale up:

```bash
kubectl get pods -n default -w
# Pod should appear with 2/2 containers (runtime + injected sidecar)
```

Check the sidecar logs:

```bash
POD=$(kubectl get pods -n default -l app.kubernetes.io/name=hello -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n default $POD -c asya-sidecar --tail=10
# Should show: "Runtime call completed" and "SQS message sent successfully"
```

After the cooldown period (30s + HPA stabilization), the pod scales back to zero:

```bash
kubectl get deployment hello -n default
# READY should show 0/0
```

## 10. Test Scale-to-N

Send a batch of messages with proper envelope format to trigger multiple replicas:

```bash
kubectl port-forward -n localstack svc/localstack 4566:4566 &
sleep 3

QUEUE_URL=http://sqs.us-east-1.localhost.localstack.cloud:4566/000000000000/asya-default-hello

for i in $(seq 1 100); do
  AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
    aws --endpoint-url=http://localhost:4566 --region us-east-1 \
    sqs send-message \
    --queue-url "$QUEUE_URL" \
    --message-body "{\"id\":\"batch-$i\",\"route\":{\"actors\":[\"hello\"],\"current\":0},\"headers\":{},\"payload\":{\"name\":\"User-$i\"}}" \
    --no-cli-pager > /dev/null
done

echo "Sent 100 messages"
kill %1 2>/dev/null
```

Watch replicas scale up:

```bash
kubectl get deployment hello -n default -w
# READY should increase beyond 1 (up to maxReplicas=10)
```

After all messages are processed and the cooldown period passes, replicas scale back to zero.

## 11. Test Resilience

Verify that Crossplane re-creates deleted resources:

```bash
# Delete the deployment
kubectl delete deployment hello -n default

# Wait for Crossplane to re-create it (should take a few seconds with watch enabled)
sleep 10
kubectl get deployment hello -n default
# Deployment should exist again

# Delete the ScaledObject
kubectl delete scaledobject hello -n default
sleep 10
kubectl get scaledobject hello -n default
# ScaledObject should exist again
```

## 12. Test Deletion

```bash
kubectl delete asyncactor hello -n default
```

Verify all resources are cleaned up:

```bash
kubectl get queue.sqs.aws.upbound.io           # No resources
kubectl get object.kubernetes.crossplane.io     # No resources
kubectl get deployment -n default               # No resources
kubectl get scaledobject -n default             # No resources
```

## 13. Clean Up

```bash
kind delete cluster --name asya-crossplane
```

## Architecture Summary

```
                    AsyncActor Claim
                         |
                    XAsyncActor (Composite)
                         |
              +----------+----------+----------+
              |          |          |          |
           SQS Queue  Deployment  ScaledObj  TriggerAuth
           (Crossplane  (Crossplane  (Crossplane  (Crossplane
            AWS)         K8s)         K8s)         K8s)
                         |
                    Pod Creation
                         |
                    Webhook Injection
                         |
              +----------+----------+
              |                     |
         asya-runtime          asya-sidecar
         (user handler)        (message router)
```

- **Crossplane Compositions** manage infrastructure: SQS queues, Deployments, KEDA ScaledObjects
- **asya-injector webhook** injects the sidecar at pod creation time
- **KEDA** handles autoscaling based on SQS queue depth
- Deletion of the AsyncActor claim cascades to all managed resources
