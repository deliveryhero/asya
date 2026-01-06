<!--
IMPORTANT: This file is tested as part of e2e test suite: /testing/e2e/tests/test_quickstart_readme.py
- All ```bash commands are executed during testing
- All typed code blocks (```python, ```yaml, ```dockerfile, etc.) with first line as "# filename" are written to files
-->
# Getting Started with Asya🎭 Locally

**Core idea**: Build multi-step AI/ML pipelines where each step deployed as an [actor](https://en.wikipedia.org/wiki/Actor_model) and scales independently. No infrastructure code in your code - just pure Python.

## What You'll Learn

- Create a Kind cluster to run Kubernetes locally in Docker, and install KEDA for autoscaling
- Deploy the Asya operator with SQS transport (running via LocalStack)
- Build and deploy your first actor with scale-to-zero capability
- Test autoscaling by sending messages to actor queues
- Optionally add S3 storage, MCP gateway, and Prometheus monitoring

## Prerequisites

Before you begin, install:

- [Docker](https://www.docker.com/get-started/) 24+
- [kubectl](https://kubernetes.io/docs/tasks/tools/) 1.28+
- [Helm](https://helm.sh/docs/intro/install/) 3.12+
- [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) 0.20+

## Setup Options

Choose your setup based on your needs:

- **[Minimal Setup](#minimal-setup)** - KEDA + SQS + Asya Operator (core functionality only)
- **[+ S3 Storage](#add-s3-storage-optional)** - Add persistence of the result message
- **[+ Asya Gateway](#add-gateway-optional)** - Add MCP HTTP API with PostgreSQL
- **[+ Prometheus](#add-prometheus-optional)** - Add observability

## Initial Setup

### 1. Create Kind Cluster

Create Kind configuration file:
```yaml
# kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 8080
    protocol: TCP
```

Create Kind cluster:
```bash
kind create cluster --name asya-local --config kind-config.yaml
kubectl config use-context kind-asya-local
```

## Minimal Setup

**What you get**: Core actor framework with SQS transport and autoscaling

### 1. Install KEDA

```bash
helm repo add kedacore https://kedacore.github.io/charts --force-update
helm install keda kedacore/keda \
  --namespace keda-system \
  --create-namespace \
  --timeout=3m
```

### 2. Install LocalStack (SQS)

LocalStack provides local AWS SQS emulation:

```bash
helm repo add localstack https://helm.localstack.cloud --force-update
helm install localstack localstack/localstack \
  --namespace asya-system \
  --create-namespace \
  --set image.tag=latest \
  --timeout=3m

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=localstack \
  -n asya-system --timeout=120s || true

kubectl get pods -l app.kubernetes.io/name=localstack -n asya-system
```
<!-- TEST: sleep 15 -->

### 3. Install Asya🎭 Operator

Install `AsyncActor` CRD:

```bash
kubectl apply -f https://github.com/deliveryhero/asya/releases/latest/download/asya-crds.yaml
```

Add Helm repository:

```bash
helm repo add asya https://asya.sh/charts --force-update
#helm repo update  # to re-download repos
```

Create AWS credentials secret:

```bash
kubectl create secret generic sqs-secret \
  --namespace asya-system \
  --from-literal=access-key-id=test \
  --from-literal=secret-access-key=test \
  --dry-run=client -o yaml | kubectl apply -f -
```

Install operator:

```yaml
# operator-values.yaml
transports:
  sqs:
    enabled: true
    config:
      region: us-east-1
      accountId: "000000000000"
      endpoint: http://localstack.asya-system.svc.cluster.local:4566
      credentials:
        accessKeyIdSecretRef:
          name: sqs-secret
          key: access-key-id
        secretAccessKeySecretRef:
          name: sqs-secret
          key: secret-access-key
```

```bash
helm install asya-operator asya/asya-operator \
  -n asya-system \
  --create-namespace \
  -f operator-values.yaml \
  --timeout=3m

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-operator \
  -n asya-system --timeout=120s || true

kubectl get pods -l app.kubernetes.io/name=asya-operator -n asya-system
# NAME                             READY   STATUS    RESTARTS   AGE
# asya-operator-7c8cdc4ff4-4qj2f   1/1     Running   0          40s
```

In order to debug 🎭 behavior (e.g. if scaling doesn't work), it's good to check operator logs:
```bash
kubectl -n asya-system logs -l app.kubernetes.io/name=asya-operator
```

### 4. Deploy Your First Actor

Write a handler:

```python
# handler.py
import time

def process(payload: dict) -> dict:
    time.sleep(1)  # simulate workload
    return {
        **payload,
        "greeting": f"Hello, {payload.get('name', 'World')}!"
    }
```

Build a docker image and load it to kind context (in real world, use CI to build and push packages automatically):

```dockerfile
# Dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY handler.py .
```

```bash
docker build -t my-hello-actor:latest .
kind load docker-image my-hello-actor:latest --name asya-local
```

Deploy the actor:

```yaml
# hello-actor.yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: hello
  namespace: default
spec:
  transport: sqs
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5  # for each 5 messages in queue create 1 new pod
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-hello-actor:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: "handler.process"
          - name: PYTHONPATH
            value: /app
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"
          - name: AWS_REGION
            value: "us-east-1"
```

```bash
kubectl apply -f hello-actor.yaml

# Wait for AsyncActor to be recognized by operator
timeout 30s sh -c '
  until kubectl get asya hello &>/dev/null; do
    echo "Waiting for AsyncActor hello to be created..."
    sleep 1
  done
' && echo "[+] AsyncActor hello created"

kubectl get asya
# NAME    STATUS    RUNNING   FAILING   TOTAL   DESIRED   MIN   MAX   LAST-SCALE   AGE
# hello   Napping   0         0         0       0         0     10    -            18s
```
<!-- # kubectl get deployment -l asya.sh/asya=hello -->

The actor is in `Napping` state with 0 replicas, demonstrating scale-to-zero capability. It will automatically scale up when messages arrive in the queue.
See more on actor states [here](/docs/architecture/asya-operator.md#status-values).

### 5. Test the Actor

Send a message to the actor's SQS queue:

```bash
MSG='{"id":"test-123","route":{"actors":["hello"],"current":0},"payload":{"name":"Asya"}}'

kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace default \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello \
      --message-body '$MSG'
  "
```

Watch the actor scale up and process the message (timeout after 60s):


Read the logs using `kubectl logs` and find the greeting message (with timeout):

```bash
timeout 30s sh -c '
  until kubectl logs -l asya.sh/asya=hello -c asya-runtime | tee /dev/stderr | grep -q "greeting"; do
    sleep 1
  done
' && echo "[+] Found expected greeting in logs"
```

Expected output should contain:
```py
user_func returned: {'name': 'Asya', 'greeting': 'Hello, Asya!'}
```

Watch horizontal autoscaling by sending 25 messages to trigger multiple pods:

```bash
MSG='{"id":"test-123","route":{"actors":["hello"],"current":0},"payload":{"name":"Asya"}}'

kubectl run send-many-messages --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace default \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    for i in {1..25}; do
      aws sqs send-message \
        --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
        --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello \
        --message-body '$MSG' &
    done
    wait
    echo '[+] All 25 messages sent'
  "
```

Watch the actor scale up to 5 pods (25 messages / 5 messages per pod):

```bash
timeout 60s kubectl get asya hello -w || true
```


## Add S3 Storage (Optional)

**What you get**: Pipeline completion with result persistence to S3

### 1. Create S3 Buckets

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- /bin/bash -c "
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-results
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-errors
  "
```

### 2. Install Crew Actors

Crew actors are pre-defined system actors proved by the framework to handle typical operations like message persistence (`happy-end` and `error-end`):

```yaml
# crew-values.yaml
happy-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_GATEWAY_URL
            value: ""  # Set this when gateway is installed
          - name: ASYA_S3_BUCKET
            value: "asya-results"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.asya-system.svc.cluster.local:4566"
          - name: ASYA_S3_REGION
            value: "us-east-1"
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"

error-end:
  transport: sqs
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          env:
          - name: ASYA_GATEWAY_URL
            value: ""  # Set this when gateway is installed
          - name: ASYA_S3_BUCKET
            value: "asya-errors"
          - name: ASYA_S3_ENDPOINT
            value: "http://localstack.asya-system.svc.cluster.local:4566"
          - name: ASYA_S3_REGION
            value: "us-east-1"
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"
```

```bash
helm install asya-crew asya/asya-crew \
  -n asya-system \
  -f crew-values.yaml \
  --timeout=3m

# Wait for crew actors to be ready
kubectl wait --for=condition=ready pod -l asya.sh/asya=happy-end -n asya-system --timeout=60s
kubectl wait --for=condition=ready pod -l asya.sh/asya=error-end -n asya-system --timeout=60s
```
<!-- TEST: kubectl get pods -n asya-system | grep -E '(happy-end|error-end)' || true -->
<!-- TEST: sleep 10 -->
<!-- TEST: kubectl logs -l asya.sh/asya=happy-end -n asya-system -c asya-runtime --tail=50[+] All 25 messages sent
pod "send-many-messages" deleted
  [+] PASSED
[14/37] Testing block:
  timeout 60s kubectl get asya hello -w || true...
  [Running...]
NAME    STATUS          RUNNING   FAILING   TOTAL   DESIRED   MIN   MAX   LAST-SCALE    AGE
hello   WorkloadError   1         1         2       2         0     10    0s ago (up)   20s
hello   Running         2         0         2       2         0     10    0s ago (up)   21s
hello   WorkloadError   2         1         2       6         0     10    10s ago (up)   31s
hello   WorkloadError   2         4         6       6         0     10    10s ago (up)   31s
hello   WorkloadError   2         4         6       6         0     10    10s ago (up)   36s
hello   Running         6         0         6       6         0     10    0s ago (up)    36s
  [+] PASSED
[15/37] Testing block:
  kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespa...
  [Running...]
make_bucket: asya-results
make_bucket: asya-errors
pod "aws-cli" deleted
  [+] PASSED
[16/37] Testing block:
  helm install asya-crew asya/asya-crew \
  -n asya-system \
  -f crew-values.yaml...
  [Running...]
  [TEST commands will execute: 4 command(s)]
NAME: asya-crew
LAST DEPLOYED: Tue Jan  6 01:59:40 2026
NAMESPACE: asya-system
STATUS: deployed
REVISION: 1
TEST SUITE: None
[TEST] Executing: kubectl get pods -n asya-system | grep -E '(happy-end|error-end)' || true
error-end-54dd5c4dbc-cnbx2       1/2     CrashLoopBackOff   4 (19s ago)   2m
happy-end-66bb4796dd-lrp97       1/2     CrashLoopBackOff   4 (19s ago)   2m
[TEST] Executing: sleep 10
[TEST] Executing: kubectl logs -l asya.sh/asya=happy-end -n asya-system -c asya-runtime --tail=50 || echo "[!] No happy-end logs available"
2026-01-06 02:01:21 - asya.runtime - INFO - Asya Actor Runtime starting with handler: '' (mode: envelope, validation: False)
2026-01-06 02:01:21 - asya.runtime - CRITICAL - FATAL: ASYA_HANDLER not set
[TEST] Executing: kubectl logs -l asya.sh/asya=error-end -n asya-system -c asya-runtime --tail=50 || echo "[!] No error-end logs available"
2026-01-06 02:01:21 - asya.runtime - INFO - Asya Actor Runtime starting with handler: '' (mode: envelope, validation: False)
2026-01-06 02:01:21 - asya.runtime - CRITICAL - FATAL: ASYA_HANDLER not set
  [+] PASSED
[17/37] Testing block:
  # Send a message through hello actor
MSG='{"id":"s3-test-001","route":{"actors":...
  [Running...]
{
    "MD5OfMessageBody": "0dadeae21f5d50ffd65494474468ae66",
    "MessageId": "505f401a-8411-4e6f-98b5-0c3273757ae2"
}
pod "aws-cli" deleted
  [+] PASSED
[18/37] Testing block:
  # Poll until S3 object appears (with 60s timeout)
timeout 60s sh -c '
  until ku...
  [Running...]
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
  [-] FAILED (exit code: 124)
============================================================
FAILURE DIAGNOSTICS:
============================================================
Checking cluster state...
NAMESPACE            NAME                                               READY   STATUS             RESTARTS        AGE
asya-system          asya-operator-58476fb94b-8dvlr                     1/1     Running            0               5m15s
asya-system          error-end-54dd5c4dbc-cnbx2                         1/2     CrashLoopBackOff   5 (10s ago)     3m14s
asya-system          happy-end-66bb4796dd-lrp97                         1/2     CrashLoopBackOff   5 (7s ago)      3m14s
asya-system          localstack-7f78c7d9cd-z8z6g                        1/1     Running            0               5m28s
default              hello-67bfcb7994-94hk5                             2/2     Running            0               4m27s
default              hello-67bfcb7994-j62lm                             2/2     Running            0               4m7s
default              hello-67bfcb7994-js9nn                             2/2     Running            0               4m7s
default              hello-67bfcb7994-lx5fv                             2/2     Running            0               4m7s
default              hello-67bfcb7994-pdnkm                             2/2     Running            0               4m22s
default              hello-67bfcb7994-wc9zg                             2/2     Running            0               4m7s
keda-system          keda-admission-webhooks-7698d4c5bb-b6zxh           1/1     Running            0               5m28s
keda-system          keda-operator-7ccb48657b-mx5jv                     1/1     Running            1 (4m59s ago)   5m28s
keda-system          keda-operator-metrics-apiserver-854498586f-pm9b9   1/1     Running            0               5m28s
kube-system          coredns-7c65d6cfc9-m6wfd                           1/1     Running            0               5m28s
kube-system          coredns-7c65d6cfc9-mpqw9                           1/1     Running            0               5m28s
kube-system          etcd-asya-local-control-plane                      1/1     Running            0               5m36s
kube-system          kindnet-lxkzz                                      1/1     Running            0               5m28s
kube-system          kube-apiserver-asya-local-control-plane            1/1     Running            0               5m36s
kube-system          kube-controller-manager-asya-local-control-plane   1/1     Running            0               5m35s
kube-system          kube-proxy-vlwgv                                   1/1     Running            0               5m28s
kube-system          kube-scheduler-asya-local-control-plane            1/1     Running            0               5m35s
local-path-storage   local-path-provisioner-57c5987fd4-9pdfc            1/1     Running            0               5m28s
Checking services...
NAMESPACE     NAME                              TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        AGE
asya-system   asya-operator-metrics             ClusterIP   10.96.115.225   <none>        8080/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       5m15s
asya-system   localstack                        NodePort    10.96.33.12     <none>        4566:31566/TCP,4510:30796/TCP,4511:31545/TCP,4512:30849/TCP,4513:32520/TCP,4514:32388/TCP,4515:32405/TCP,4516:30338/TCP,4517:31313/TCP,4518:31105/TCP,4519:32241/TCP,4520:31456/TCP,4521:32465/TCP,4522:31037/TCP,4523:32101/TCP,4524:30807/TCP,4525:32094/TCP,4526:30895/TCP,4527:31909/TCP,4528:30620/TCP,4529:32560/TCP,4530:31845/TCP,4531:31320/TCP,4532:30443/TCP,4533:30456/TCP,4534:30821/TCP,4535:31120/TCP,4536:30406/TCP,4537:30632/TCP,4538:32299/TCP,4539:32555/TCP,4540:31231/TCP,4541:32679/TCP,4542:31724/TCP,4543:32722/TCP,4544:30149/TCP,4545:31438/TCP,4546:32052/TCP,4547:30486/TCP,4548:31578/TCP,4549:32432/TCP,4550:30298/TCP,4551:31187/TCP,4552:30801/TCP,4553:32553/TCP,4554:32150/TCP,4555:30980/TCP,4556:31007/TCP,4557:31595/TCP,4558:31511/TCP,4559:30442/TCP   5m32s
default       kubernetes                        ClusterIP   10.96.0.1       <none>        443/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        5m36s
keda-system   keda-admission-webhooks           ClusterIP   10.96.127.219   <none>        443/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        5m33s
keda-system   keda-operator                     ClusterIP   10.96.11.156    <none>        9666/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       5m33s
keda-system   keda-operator-metrics-apiserver   ClusterIP   10.96.9.145     <none>        443/TCP,8080/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               5m33s
kube-system   kube-dns                          ClusterIP   10.96.0.10      <none>        53/UDP,53/TCP,9153/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         5m35s
============================================================
----------------------------- Captured stderr call -----------------------------
2026-01-06 01:58:17 - asya.runtime - INFO - Socket permissions set to 0o666
2026-01-06 01:58:17 - asya.runtime - INFO - Socket server listening on /var/run/asya/asya-runtime.sock
2026-01-06 01:58:17 - asya.runtime - INFO - Runtime ready signal created: /var/run/asya/runtime-ready
2026-01-06 01:58:24 - asya.runtime - WARNING - Client disconnected
2026-01-06 01:58:24 - asya.runtime - INFO - [DIAG] Starting handler execution, mode=payload, envelope_id=test-123
2026-01-06 01:58:24 - asya.runtime - INFO - [DIAG] Calling user_func with payload: {'name': 'Asya'}
2026-01-06 01:58:25 - asya.runtime - WARNING - Received signal 15, shutting down...
2026-01-06 01:58:25 - asya.runtime - INFO - [DIAG] user_func returned: {'name': 'Asya', 'greeting': 'Hello, Asya!'}
2026-01-06 01:58:25 - asya.runtime - INFO - [DIAG] Handler completed successfully: returning 1 response(s)
2026-01-06 01:58:25 - asya.runtime - WARNING - Received signal None, shutting down...

+ MSG='{"id":"test-123","route":{"actors":["hello"],"current":0},"payload":{"name":"Asya"}}'
+ kubectl run send-many-messages --rm -i --restart=Never --image=amazon/aws-cli --namespace default --env=AWS_ACCESS_KEY_ID=test --env=AWS_SECRET_ACCESS_KEY=test --env=AWS_DEFAULT_REGION=us-east-1 --command -- sh -c '
    for i in {1..25}; do
      aws sqs send-message         --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566         --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello         --message-body '\''{"id":"test-123","route":{"actors":["hello"],"current":0},"payload":{"name":"Asya"}}'\'' &
    done
    wait
    echo '\''[+] All 25 messages sent'\''
  '
If you don't see a command prompt, try pressing enter.
+ timeout 60s kubectl get asya hello -w
+ true
+ kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli --namespace asya-system --env=AWS_ACCESS_KEY_ID=test --env=AWS_SECRET_ACCESS_KEY=test --env=AWS_DEFAULT_REGION=us-east-1 --command -- /bin/bash -c '
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-results
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-errors
  '
If you don't see a command prompt, try pressing enter.
+ helm install asya-crew asya/asya-crew -n asya-system -f crew-values.yaml --timeout=3m
+ kubectl wait --for=condition=ready pod -l asya.sh/asya=happy-end -n asya-system --timeout=60s
error: timed out waiting for the condition on pods/happy-end-66bb4796dd-lrp97
+ kubectl wait --for=condition=ready pod -l asya.sh/asya=error-end -n asya-system --timeout=60s
error: timed out waiting for the condition on pods/error-end-54dd5c4dbc-cnbx2
+ echo '[TEST] Executing: kubectl get pods -n asya-system | grep -E '\''(happy-end|error-end)'\'' || true'
+ kubectl get pods -n asya-system
+ grep -E '(happy-end|error-end)'
+ echo '[TEST] Executing: sleep 10'
+ sleep 10
+ echo '[TEST] Executing: kubectl logs -l asya.sh/asya=happy-end -n asya-system -c asya-runtime --tail=50 || echo "[!] No happy-end logs available"'
+ kubectl logs -l asya.sh/asya=happy-end -n asya-system -c asya-runtime --tail=50
+ echo '[TEST] Executing: kubectl logs -l asya.sh/asya=error-end -n asya-system -c asya-runtime --tail=50 || echo "[!] No error-end logs available"'
+ kubectl logs -l asya.sh/asya=error-end -n asya-system -c asya-runtime --tail=50
+ MSG='{"id":"s3-test-001","route":{"actors":["hello"],"current":0},"payload":{"name":"S3 Test"}}'
+ kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli --namespace default --env=AWS_ACCESS_KEY_ID=test --env=AWS_SECRET_ACCESS_KEY=test --env=AWS_DEFAULT_REGION=us-east-1 --command -- sh -c '
    aws sqs send-message       --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566       --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello       --message-body '\''{"id":"s3-test-001","route":{"actors":["hello"],"current":0},"payload":{"name":"S3 Test"}}'\''
  '
If you don't see a command prompt, try pressing enter.
warning: couldn't attach to pod/aws-cli, falling back to streaming logs: Internal error occurred: unable to upgrade connection: container aws-cli not found in pod aws-cli_default
+ timeout 60s sh -c '
  until kubectl run "aws-cli-$(date +%s%N)" --rm -i --restart=Never --image=amazon/aws-cli \
    --namespace asya-system \
    --env="AWS_ACCESS_KEY_ID=test" \
    --env="AWS_SECRET_ACCESS_KEY=test" \
    --env="AWS_DEFAULT_REGION=us-east-1" \
    --command -- /bin/bash -c "
      aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
        s3 ls s3://asya-results/s3-test-001.json 2>/dev/null
    " | grep -q "s3-test-001.json"; do
    echo "Waiting for S3 object s3-test-001.json..."
    sleep 5
  done
'
pod asya-system/aws-cli-1767664914807577153 terminated (Error)
pod asya-system/aws-cli-1767664922780024172 terminated (Error)
pod asya-system/aws-cli-1767664930795786578 terminated (Error)
pod asya-system/aws-cli-1767664938812121551 terminated (Error)
pod asya-system/aws-cli-1767664946829107455 terminated (Error)
pod asya-system/aws-cli-1767664954849514528 terminated (Error)
pod asya-system/aws-cli-1767664962885237295 terminated (Error)
pod asya-system/aws-cli-1767664970898702006 terminated (Error)
--------------------------- Captured stdout teardown ---------------------------
================================================================================
DOCS TEST TEARDOWN: asya-local
================================================================================
[.] Post-cleanup: Deleting cluster: asya-local
[+] Cluster deleted: asya-local
================================================================================
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.13.8-final-0 ________________
=========================== short test summary info ============================
FAILED tests/test_quickstart_readme.py::test_quickstart_readme_commands - Failed: Block #18 failed with exit code 124
Command: # Poll until S3 object appears (with 60s timeout)
timeout 60s sh -c '
  until kubectl run "aws-cli-$...
======================== 1 failed in 361.16s (0:06:01) =========================
make: *** [Makefile:35: test] Error 1 || echo "[!] No happy-end logs available" -->
<!-- TEST: kubectl logs -l asya.sh/asya=error-end -n asya-system -c asya-runtime --tail=50[+] All 25 messages sent
pod "send-many-messages" deleted
  [+] PASSED
[14/37] Testing block:
  timeout 60s kubectl get asya hello -w || true...
  [Running...]
NAME    STATUS          RUNNING   FAILING   TOTAL   DESIRED   MIN   MAX   LAST-SCALE    AGE
hello   WorkloadError   1         1         2       2         0     10    0s ago (up)   20s
hello   Running         2         0         2       2         0     10    0s ago (up)   21s
hello   WorkloadError   2         1         2       6         0     10    10s ago (up)   31s
hello   WorkloadError   2         4         6       6         0     10    10s ago (up)   31s
hello   WorkloadError   2         4         6       6         0     10    10s ago (up)   36s
hello   Running         6         0         6       6         0     10    0s ago (up)    36s
  [+] PASSED
[15/37] Testing block:
  kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespa...
  [Running...]
make_bucket: asya-results
make_bucket: asya-errors
pod "aws-cli" deleted
  [+] PASSED
[16/37] Testing block:
  helm install asya-crew asya/asya-crew \
  -n asya-system \
  -f crew-values.yaml...
  [Running...]
  [TEST commands will execute: 4 command(s)]
NAME: asya-crew
LAST DEPLOYED: Tue Jan  6 01:59:40 2026
NAMESPACE: asya-system
STATUS: deployed
REVISION: 1
TEST SUITE: None
[TEST] Executing: kubectl get pods -n asya-system | grep -E '(happy-end|error-end)' || true
error-end-54dd5c4dbc-cnbx2       1/2     CrashLoopBackOff   4 (19s ago)   2m
happy-end-66bb4796dd-lrp97       1/2     CrashLoopBackOff   4 (19s ago)   2m
[TEST] Executing: sleep 10
[TEST] Executing: kubectl logs -l asya.sh/asya=happy-end -n asya-system -c asya-runtime --tail=50 || echo "[!] No happy-end logs available"
2026-01-06 02:01:21 - asya.runtime - INFO - Asya Actor Runtime starting with handler: '' (mode: envelope, validation: False)
2026-01-06 02:01:21 - asya.runtime - CRITICAL - FATAL: ASYA_HANDLER not set
[TEST] Executing: kubectl logs -l asya.sh/asya=error-end -n asya-system -c asya-runtime --tail=50 || echo "[!] No error-end logs available"
2026-01-06 02:01:21 - asya.runtime - INFO - Asya Actor Runtime starting with handler: '' (mode: envelope, validation: False)
2026-01-06 02:01:21 - asya.runtime - CRITICAL - FATAL: ASYA_HANDLER not set
  [+] PASSED
[17/37] Testing block:
  # Send a message through hello actor
MSG='{"id":"s3-test-001","route":{"actors":...
  [Running...]
{
    "MD5OfMessageBody": "0dadeae21f5d50ffd65494474468ae66",
    "MessageId": "505f401a-8411-4e6f-98b5-0c3273757ae2"
}
pod "aws-cli" deleted
  [+] PASSED
[18/37] Testing block:
  # Poll until S3 object appears (with 60s timeout)
timeout 60s sh -c '
  until ku...
  [Running...]
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
Waiting for S3 object s3-test-001.json...
  [-] FAILED (exit code: 124)
============================================================
FAILURE DIAGNOSTICS:
============================================================
Checking cluster state...
NAMESPACE            NAME                                               READY   STATUS             RESTARTS        AGE
asya-system          asya-operator-58476fb94b-8dvlr                     1/1     Running            0               5m15s
asya-system          error-end-54dd5c4dbc-cnbx2                         1/2     CrashLoopBackOff   5 (10s ago)     3m14s
asya-system          happy-end-66bb4796dd-lrp97                         1/2     CrashLoopBackOff   5 (7s ago)      3m14s
asya-system          localstack-7f78c7d9cd-z8z6g                        1/1     Running            0               5m28s
default              hello-67bfcb7994-94hk5                             2/2     Running            0               4m27s
default              hello-67bfcb7994-j62lm                             2/2     Running            0               4m7s
default              hello-67bfcb7994-js9nn                             2/2     Running            0               4m7s
default              hello-67bfcb7994-lx5fv                             2/2     Running            0               4m7s
default              hello-67bfcb7994-pdnkm                             2/2     Running            0               4m22s
default              hello-67bfcb7994-wc9zg                             2/2     Running            0               4m7s
keda-system          keda-admission-webhooks-7698d4c5bb-b6zxh           1/1     Running            0               5m28s
keda-system          keda-operator-7ccb48657b-mx5jv                     1/1     Running            1 (4m59s ago)   5m28s
keda-system          keda-operator-metrics-apiserver-854498586f-pm9b9   1/1     Running            0               5m28s
kube-system          coredns-7c65d6cfc9-m6wfd                           1/1     Running            0               5m28s
kube-system          coredns-7c65d6cfc9-mpqw9                           1/1     Running            0               5m28s
kube-system          etcd-asya-local-control-plane                      1/1     Running            0               5m36s
kube-system          kindnet-lxkzz                                      1/1     Running            0               5m28s
kube-system          kube-apiserver-asya-local-control-plane            1/1     Running            0               5m36s
kube-system          kube-controller-manager-asya-local-control-plane   1/1     Running            0               5m35s
kube-system          kube-proxy-vlwgv                                   1/1     Running            0               5m28s
kube-system          kube-scheduler-asya-local-control-plane            1/1     Running            0               5m35s
local-path-storage   local-path-provisioner-57c5987fd4-9pdfc            1/1     Running            0               5m28s
Checking services...
NAMESPACE     NAME                              TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        AGE
asya-system   asya-operator-metrics             ClusterIP   10.96.115.225   <none>        8080/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       5m15s
asya-system   localstack                        NodePort    10.96.33.12     <none>        4566:31566/TCP,4510:30796/TCP,4511:31545/TCP,4512:30849/TCP,4513:32520/TCP,4514:32388/TCP,4515:32405/TCP,4516:30338/TCP,4517:31313/TCP,4518:31105/TCP,4519:32241/TCP,4520:31456/TCP,4521:32465/TCP,4522:31037/TCP,4523:32101/TCP,4524:30807/TCP,4525:32094/TCP,4526:30895/TCP,4527:31909/TCP,4528:30620/TCP,4529:32560/TCP,4530:31845/TCP,4531:31320/TCP,4532:30443/TCP,4533:30456/TCP,4534:30821/TCP,4535:31120/TCP,4536:30406/TCP,4537:30632/TCP,4538:32299/TCP,4539:32555/TCP,4540:31231/TCP,4541:32679/TCP,4542:31724/TCP,4543:32722/TCP,4544:30149/TCP,4545:31438/TCP,4546:32052/TCP,4547:30486/TCP,4548:31578/TCP,4549:32432/TCP,4550:30298/TCP,4551:31187/TCP,4552:30801/TCP,4553:32553/TCP,4554:32150/TCP,4555:30980/TCP,4556:31007/TCP,4557:31595/TCP,4558:31511/TCP,4559:30442/TCP   5m32s
default       kubernetes                        ClusterIP   10.96.0.1       <none>        443/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        5m36s
keda-system   keda-admission-webhooks           ClusterIP   10.96.127.219   <none>        443/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        5m33s
keda-system   keda-operator                     ClusterIP   10.96.11.156    <none>        9666/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       5m33s
keda-system   keda-operator-metrics-apiserver   ClusterIP   10.96.9.145     <none>        443/TCP,8080/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               5m33s
kube-system   kube-dns                          ClusterIP   10.96.0.10      <none>        53/UDP,53/TCP,9153/TCP                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         5m35s
============================================================
----------------------------- Captured stderr call -----------------------------
2026-01-06 01:58:17 - asya.runtime - INFO - Socket permissions set to 0o666
2026-01-06 01:58:17 - asya.runtime - INFO - Socket server listening on /var/run/asya/asya-runtime.sock
2026-01-06 01:58:17 - asya.runtime - INFO - Runtime ready signal created: /var/run/asya/runtime-ready
2026-01-06 01:58:24 - asya.runtime - WARNING - Client disconnected
2026-01-06 01:58:24 - asya.runtime - INFO - [DIAG] Starting handler execution, mode=payload, envelope_id=test-123
2026-01-06 01:58:24 - asya.runtime - INFO - [DIAG] Calling user_func with payload: {'name': 'Asya'}
2026-01-06 01:58:25 - asya.runtime - WARNING - Received signal 15, shutting down...
2026-01-06 01:58:25 - asya.runtime - INFO - [DIAG] user_func returned: {'name': 'Asya', 'greeting': 'Hello, Asya!'}
2026-01-06 01:58:25 - asya.runtime - INFO - [DIAG] Handler completed successfully: returning 1 response(s)
2026-01-06 01:58:25 - asya.runtime - WARNING - Received signal None, shutting down...

+ MSG='{"id":"test-123","route":{"actors":["hello"],"current":0},"payload":{"name":"Asya"}}'
+ kubectl run send-many-messages --rm -i --restart=Never --image=amazon/aws-cli --namespace default --env=AWS_ACCESS_KEY_ID=test --env=AWS_SECRET_ACCESS_KEY=test --env=AWS_DEFAULT_REGION=us-east-1 --command -- sh -c '
    for i in {1..25}; do
      aws sqs send-message         --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566         --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello         --message-body '\''{"id":"test-123","route":{"actors":["hello"],"current":0},"payload":{"name":"Asya"}}'\'' &
    done
    wait
    echo '\''[+] All 25 messages sent'\''
  '
If you don't see a command prompt, try pressing enter.
+ timeout 60s kubectl get asya hello -w
+ true
+ kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli --namespace asya-system --env=AWS_ACCESS_KEY_ID=test --env=AWS_SECRET_ACCESS_KEY=test --env=AWS_DEFAULT_REGION=us-east-1 --command -- /bin/bash -c '
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-results
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 s3 mb s3://asya-errors
  '
If you don't see a command prompt, try pressing enter.
+ helm install asya-crew asya/asya-crew -n asya-system -f crew-values.yaml --timeout=3m
+ kubectl wait --for=condition=ready pod -l asya.sh/asya=happy-end -n asya-system --timeout=60s
error: timed out waiting for the condition on pods/happy-end-66bb4796dd-lrp97
+ kubectl wait --for=condition=ready pod -l asya.sh/asya=error-end -n asya-system --timeout=60s
error: timed out waiting for the condition on pods/error-end-54dd5c4dbc-cnbx2
+ echo '[TEST] Executing: kubectl get pods -n asya-system | grep -E '\''(happy-end|error-end)'\'' || true'
+ kubectl get pods -n asya-system
+ grep -E '(happy-end|error-end)'
+ echo '[TEST] Executing: sleep 10'
+ sleep 10
+ echo '[TEST] Executing: kubectl logs -l asya.sh/asya=happy-end -n asya-system -c asya-runtime --tail=50 || echo "[!] No happy-end logs available"'
+ kubectl logs -l asya.sh/asya=happy-end -n asya-system -c asya-runtime --tail=50
+ echo '[TEST] Executing: kubectl logs -l asya.sh/asya=error-end -n asya-system -c asya-runtime --tail=50 || echo "[!] No error-end logs available"'
+ kubectl logs -l asya.sh/asya=error-end -n asya-system -c asya-runtime --tail=50
+ MSG='{"id":"s3-test-001","route":{"actors":["hello"],"current":0},"payload":{"name":"S3 Test"}}'
+ kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli --namespace default --env=AWS_ACCESS_KEY_ID=test --env=AWS_SECRET_ACCESS_KEY=test --env=AWS_DEFAULT_REGION=us-east-1 --command -- sh -c '
    aws sqs send-message       --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566       --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello       --message-body '\''{"id":"s3-test-001","route":{"actors":["hello"],"current":0},"payload":{"name":"S3 Test"}}'\''
  '
If you don't see a command prompt, try pressing enter.
warning: couldn't attach to pod/aws-cli, falling back to streaming logs: Internal error occurred: unable to upgrade connection: container aws-cli not found in pod aws-cli_default
+ timeout 60s sh -c '
  until kubectl run "aws-cli-$(date +%s%N)" --rm -i --restart=Never --image=amazon/aws-cli \
    --namespace asya-system \
    --env="AWS_ACCESS_KEY_ID=test" \
    --env="AWS_SECRET_ACCESS_KEY=test" \
    --env="AWS_DEFAULT_REGION=us-east-1" \
    --command -- /bin/bash -c "
      aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
        s3 ls s3://asya-results/s3-test-001.json 2>/dev/null
    " | grep -q "s3-test-001.json"; do
    echo "Waiting for S3 object s3-test-001.json..."
    sleep 5
  done
'
pod asya-system/aws-cli-1767664914807577153 terminated (Error)
pod asya-system/aws-cli-1767664922780024172 terminated (Error)
pod asya-system/aws-cli-1767664930795786578 terminated (Error)
pod asya-system/aws-cli-1767664938812121551 terminated (Error)
pod asya-system/aws-cli-1767664946829107455 terminated (Error)
pod asya-system/aws-cli-1767664954849514528 terminated (Error)
pod asya-system/aws-cli-1767664962885237295 terminated (Error)
pod asya-system/aws-cli-1767664970898702006 terminated (Error)
--------------------------- Captured stdout teardown ---------------------------
================================================================================
DOCS TEST TEARDOWN: asya-local
================================================================================
[.] Post-cleanup: Deleting cluster: asya-local
[+] Cluster deleted: asya-local
================================================================================
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.13.8-final-0 ________________
=========================== short test summary info ============================
FAILED tests/test_quickstart_readme.py::test_quickstart_readme_commands - Failed: Block #18 failed with exit code 124
Command: # Poll until S3 object appears (with 60s timeout)
timeout 60s sh -c '
  until kubectl run "aws-cli-$...
======================== 1 failed in 361.16s (0:06:01) =========================
make: *** [Makefile:35: test] Error 1 || echo "[!] No error-end logs available" -->

Your pipeline results are now automatically persisted to S3: whenever an actor finishes processing the last message in the route, 🎭 automatically sends it to `happy-end` actor to persist it on S3. Similarly, error messages will be sent to `error-end`.

### 3. Verify S3 Persistence

Send a test message and verify it's persisted to S3:

```bash
# Send a message through hello actor
MSG='{"id":"s3-test-001","route":{"actors":["hello"],"current":0},"payload":{"name":"S3 Test"}}'

kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace default \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello \
      --message-body '$MSG'
  "
```

Wait for the message to be processed and persisted to S3:

```bash
# Poll until S3 object appears (with 60s timeout)
timeout 60s sh -c '
  until kubectl run "aws-cli-$(date +%s%N)" --rm -i --restart=Never --image=amazon/aws-cli \
    --namespace asya-system \
    --env="AWS_ACCESS_KEY_ID=test" \
    --env="AWS_SECRET_ACCESS_KEY=test" \
    --env="AWS_DEFAULT_REGION=us-east-1" \
    --command -- /bin/bash -c "
      aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
        s3 ls s3://asya-results/s3-test-001.json 2>/dev/null
    " | grep -q "s3-test-001.json"; do
    echo "Waiting for S3 object s3-test-001.json..."
    sleep 5
  done
' && echo "[+] S3 object found: s3-test-001.json"
```

You should see an S3 object with a key like `s3-test-001.json`. Download and inspect it:

```bash
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- /bin/bash -c "
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      s3 cp s3://asya-results/s3-test-001.json - | cat
  "
```

Expected output should contain the greeting:
```json
{
  "id": "s3-test-001",
  "route": {"actors": ["hello"], "current": 1},
  "payload": {
    "name": "S3 Test",
    "greeting": "Hello, S3 Test!"
  }
}
```


## Add Gateway (Optional)

**What you get**: HTTP API, MCP tools, SSE streaming, envelope tracking

### 1. Install PostgreSQL

Persistence layer. On production setup, a managed PostgreSQL can be used. In future, if needed, we may support other databases.

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: asya-gateway-postgresql
  namespace: asya-system
spec:
  selector:
    app: postgresql
  ports:
    - port: 5432
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: asya-gateway-postgresql
  namespace: asya-system
spec:
  selector:
    matchLabels:
      app: postgresql
  template:
    metadata:
      labels:
        app: postgresql
    spec:
      containers:
        - name: postgres
          image: 'postgres:15-alpine'
          env:
            - name: POSTGRES_USER
              value: asya
            - name: POSTGRES_PASSWORD
              value: asya
            - name: POSTGRES_DB
              value: asya
EOF
```

### 2. Create PostgreSQL Secret

```bash
kubectl create secret generic asya-gateway-postgresql \
  --namespace asya-system \
  --from-literal=password=asya \
  --dry-run=client -o yaml | kubectl apply -f -
```

---

### 3. Install Gateway

```yaml
# gateway-values.yaml
image:
  repository: ghcr.io/deliveryhero/asya-gateway
  tag: latest

config:
  sqsEndpoint: http://localstack.asya-system.svc.cluster.local:4566
  sqsRegion: us-east-1
  database:
    host: asya-gateway-postgresql.asya-system.svc.cluster.local
    name: asya
    user: asya
    password: asya

env:
- name: AWS_ACCESS_KEY_ID
  value: "test"
- name: AWS_SECRET_ACCESS_KEY
  value: "test"
```

```bash
helm install asya-gateway asya/asya-gateway \
  -n asya-system \
  -f gateway-values.yaml \
  --timeout=3m

kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=asya-gateway \
  -n asya-system --timeout=120s || true

kubectl get pods -l app.kubernetes.io/name=asya-gateway -n asya-system
```

### 4. Update Operator for Gateway Integration

Update the operator configuration to include the gateway URL (so that new asyas created after this point are aware of gateway and report their statuses):

```bash
helm upgrade asya-operator asya/asya-operator \
  -n asya-system \
  -f operator-values.yaml \
  --set gatewayURL="http://asya-gateway.asya-system.svc.cluster.local:8080" \
  --timeout=3m
```

### 5. Update Crew Actors for Gateway Reporting

Update crew configuration to report status to the gateway:

```bash
helm upgrade asya-crew asya/asya-crew \
  -n asya-system \
  -f crew-values.yaml \
  --set-string 'happy-end.workload.template.spec.containers[0].env[0].value=http://asya-gateway.asya-system.svc.cluster.local:8080' \
  --set-string 'error-end.workload.template.spec.containers[0].env[0].value=http://asya-gateway.asya-system.svc.cluster.local:8080' \
  --timeout=3m
```

Wait for crew actors to be ready:

```bash
kubectl wait --for=condition=ready pod -l asya.sh/asya=happy-end \
  -n asya-system --timeout=120s || true

kubectl wait --for=condition=ready pod -l asya.sh/asya=error-end \
  -n asya-system --timeout=120s || true
```

Verify S3 persistence with gateway reporting:

```bash
# Send a test message
MSG='{"id":"gateway-test-001","route":{"actors":["hello"],"current":0},"payload":{"name":"Gateway Test"}}'

kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace default \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- sh -c "
    aws sqs send-message \
      --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      --queue-url http://localstack.asya-system.svc.cluster.local:4566/000000000000/asya-default-hello \
      --message-body '$MSG'
  "
```

Wait for processing and verify S3 persistence:

```bash
# Poll until S3 object appears (with 60s timeout)
timeout 60s sh -c '
  until kubectl run "aws-cli-$(date +%s%N)" --rm -i --restart=Never --image=amazon/aws-cli \
    --namespace asya-system \
    --env="AWS_ACCESS_KEY_ID=test" \
    --env="AWS_SECRET_ACCESS_KEY=test" \
    --env="AWS_DEFAULT_REGION=us-east-1" \
    --command -- /bin/bash -c "
      aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
        s3 ls s3://asya-results/gateway-test-001.json 2>/dev/null
    " | grep -q "gateway-test-001.json"; do
    echo "Waiting for S3 object gateway-test-001.json..."
    sleep 5
  done
' && echo "[+] S3 object found: gateway-test-001.json"

# Download and inspect the object
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- /bin/bash -c "
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      s3 cp s3://asya-results/gateway-test-001.json - | cat
  "
```

### 6. Use the Gateway

Install CLI:

```bash
pip install git+https://github.com/deliveryhero/asya.git#subdirectory=src/asya-cli
```

Port-forward and test:

```bash
kubectl port-forward -n asya-system svc/asya-gateway 8080:80 &
PORT_FORWARD_PID=$!

# Wait for port-forward to establish
timeout 30s sh -c '
  until curl -s http://localhost:8080/health &>/dev/null; do
    echo "Waiting for gateway port-forward to establish..."
    sleep 1
  done
' && echo "[+] Gateway port-forward established"

export ASYA_CLI_MCP_URL=http://localhost:8080/

# List tools
asya mcp list

# Call an actor
asya mcp call hello --name=Asya

# Stream progress
asya mcp call hello --name=Asya --stream

kill $PORT_FORWARD_PID 2>/dev/null || true
```

## Add Prometheus (Optional)

**What you get**: Metrics collection and observability

### 1. Install Prometheus

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts --force-update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --timeout=5m
```

### 2. Configure ServiceMonitors

The Asya operator exposes metrics at `:8080/metrics`. Create a ServiceMonitor:

```bash
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: asya-operator
  namespace: asya-system
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: asya-operator
  endpoints:
  - port: metrics
    interval: 30s
EOF
```

### 3. Access Grafana

```bash
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80 &
GRAFANA_PID=$!

# Wait for port-forward to establish
timeout 30s sh -c '
  until curl -s http://localhost:3000/api/health &>/dev/null; do
    echo "Waiting for Grafana port-forward to establish..."
    sleep 1
  done
' && echo "[+] Grafana port-forward established"

# Now access http://localhost:3000 in your browser
# When done:
kill $GRAFANA_PID 2>/dev/null || true
```

Default credentials: `admin` / `prom-operator`

Import Asya dashboards from the [monitoring guide](../operate/monitoring.md).

## Testing Your Setup

Send a message and watch scaling:

```bash
# Send message via MCP gateway
asya mcp call hello --name="Test"

# Watch pods scale (timeout after 60s)
timeout 60s kubectl get pods -l asya.sh/asya=hello -w || true

# Check logs
POD=$(kubectl get pods -l asya.sh/asya=hello -o name | head -1)
kubectl logs $POD -c asya-runtime
kubectl logs $POD -c asya-sidecar
```

Verify end-to-end flow with S3 persistence:

```bash
# Check envelope status via gateway
# asya mcp status <envelope-id>

# List all objects in S3 results bucket
kubectl run aws-cli --rm -i --restart=Never --image=amazon/aws-cli \
  --namespace asya-system \
  --env="AWS_ACCESS_KEY_ID=test" \
  --env="AWS_SECRET_ACCESS_KEY=test" \
  --env="AWS_DEFAULT_REGION=us-east-1" \
  --command -- /bin/bash -c "
    echo '[+] All results persisted to S3:'
    aws --endpoint-url=http://localstack.asya-system.svc.cluster.local:4566 \
      s3 ls s3://asya-results/ --recursive
  "
```

## Alternative: Quick E2E Setup

For rapid testing with all components:

```bash
cd testing/e2e
make up PROFILE=sqs-s3
```

This deploys everything in one command but uses test configurations.

## Production Deployment

For production on AWS, replace LocalStack with real AWS services:

```yaml
# operator-values.yaml for production
transports:
  sqs:
    enabled: true
    type: sqs
    config:
      region: us-east-1
      accountId: "123456789012"
      # Remove endpoint for production AWS
      actorRoleArn: "arn:aws:iam::123456789012:role/asya-actor-role"
      queues:
        autoCreate: true
        dlq:
          enabled: true
          maxRetryCount: 3
      # Use IRSA instead of static credentials
```

See [AWS EKS Installation](../install/aws-eks.md) for full production guide.

## What's Next?

### For Data Scientists

- **[Quickstart for Data Scientists](for-data-scientists.md)** - Class handlers, model loading, dynamic routing
- **[Flow DSL](../architecture/asya-flow.md)** - Write pipelines in Python-like syntax

**Use cases**:
- Multi-step LLM workflows (RAG → generate → judge → refine)
- Document processing (OCR → classify → extract → store)
- Image pipelines (resize → detect → classify → tag)

### For Platform Engineers

- **[Quickstart for Platform Engineers](for-platform-engineers.md)** - Deployment strategies, scaling policies
- **[AWS EKS Installation](../install/aws-eks.md)** - Production deployment
- **[Monitoring](../operate/monitoring.md)** - Metrics, alerts, dashboards
- **[Troubleshooting](../operate/troubleshooting.md)** - Common issues

## Learn More

- [Core Concepts](../concepts.md) - Actors, envelopes, sidecars, routing
- [Motivation](../motivation.md) - Why Asya🎭 exists, when to use it
- [Architecture](../architecture/README.md) - Deep dive into system design
- [Examples](https://github.com/deliveryhero/asya/tree/main/examples) - Sample actors and flows

## Clean Up

### Clean Up Specific Components

If you want to remove specific components while keeping the cluster:

```bash
# Remove Prometheus (if installed)
helm uninstall prometheus -n monitoring || true
kubectl delete namespace monitoring || true

# Remove Gateway (if installed)
helm uninstall asya-gateway -n asya-system || true
kubectl delete secret asya-gateway-postgresql -n asya-system || true
kubectl delete deployment asya-gateway-postgresql -n asya-system || true
kubectl delete service asya-gateway-postgresql -n asya-system || true

# Remove Crew actors (if installed)
helm uninstall asya-crew -n asya-system || true

# Remove your custom actors
kubectl delete asya hello -n default || true

# Remove Asya operator
helm uninstall asya-operator -n asya-system || true

# Remove LocalStack
helm uninstall localstack -n asya-system || true

# Remove KEDA
helm uninstall keda -n keda-system || true
kubectl delete namespace keda-system || true

# Remove CRDs
kubectl delete crd asyncactors.asya.sh || true

# Remove namespace
kubectl delete namespace asya-system || true
```

### Clean Up Everything

To completely remove the Kind cluster and all components:

```bash
kind delete cluster --name asya-local
```

---

**Next**: Choose your path - [Data Scientists](for-data-scientists.md) or [Platform Engineers](for-platform-engineers.md)
