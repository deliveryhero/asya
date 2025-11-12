
# Kubernetes-Native AI/ML Integration Targets

This document outlines Kubernetes-native AI/ML tools that Asya🎭 can integrate with to create async computation graphs.

## Integration Targets by Category

### Tier 1: Highest Value Integrations

#### 1. KAITO (Kubernetes AI Toolchain Operator)

**Priority**: ⭐⭐⭐⭐⭐

**What it does**:
- Automates deployment of AI model inference workloads on K8s
- Manages GPU provisioning and node autoscaling (especially for Azure AKS)
- Pre-configured presets for popular models (Phi-3, Llama, Mistral, etc.)

**Asya🎭 value-add**:
- **Problem KAITO solves**: Easy model deployment with GPU management
- **Problem Asya🎭 solves**: Async message routing, queue-based workload distribution, scale-to-zero
- **Combined value**: KAITO deploys models → Asya🎭 adds async computation graphs with multiple model chaining

**Integration pattern**:

```yaml
# KAITO deploys model
apiVersion: kaito.sh/v1alpha1
kind: Workspace
metadata:
  name: phi-3-embeddings
spec:
  resource:
    instanceType: Standard_NC6s_v3
  inference:
    preset:
      name: phi-3-mini-4k-instruct

---
# Asya🎭 binds async capabilities
apiVersion: asya.sh/v1alpha1
kind: AsyaBinding
metadata:
  name: phi-3-async
spec:
  workloadRef:
    kind: Deployment
    name: phi-3-embeddings
  transport:
    name: sqs
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 100
```

**Use case**:

Multi-stage AI pipeline: Text → Embeddings (KAITO+Asya🎭) → Vector DB → Retrieval (KAITO+Asya🎭) → LLM (KAITO+Asya🎭) → Response

---

#### 2. KubeRay (Ray on Kubernetes)

**Priority**: ⭐⭐⭐⭐⭐

**What it does**:
- Runs Ray distributed computing framework on K8s
- Ray Serve: Multi-model serving with autoscaling
- Supports distributed training and inference
- Native support for vLLM, DeepSpeed, tensor parallelism

**Asya🎭 value-add**:
- **Problem Ray solves**: Distributed compute, complex ML pipelines, multi-GPU inference
- **Problem Asya🎭 solves**: External queue integration (SQS/RabbitMQ), durable message routing, error handling
- **Combined value**: Ray handles multi-node inference → Asya🎭 handles cross-pipeline routing

**Integration pattern**:

```yaml
# KubeRay cluster with vLLM
apiVersion: ray.io/v1alpha1
kind: RayService
metadata:
  name: llama-serve
spec:
  serveConfig:
    applications:
    - name: llama-app
      runtime_env:
        pip: ["vllm"]

---
# Asya🎭 binds to Ray head service
apiVersion: asya.sh/v1alpha1
kind: AsyaBinding
metadata:
  name: llama-async
spec:
  workloadRef:
    kind: Deployment
    name: llama-serve-head  # Ray head node
  transport:
    name: rabbitmq
  scaling:
    enabled: false  # Ray has its own autoscaling
```

**Use case**:

Distributed LLM inference with queue buffering: Client → SQS → Asya🎭 → Ray Serve (multi-GPU vLLM) → Asya🎭 → Results

---

#### 3. KServe (Kubernetes Model Serving)

**Priority**: ⭐⭐⭐⭐

**What it does**:
- Production-ready ML serving platform (CNCF Incubating)
- Multi-framework support (TensorFlow, PyTorch, ONNX, vLLM, Triton)
- Advanced features: canary rollouts, A/B testing, explainability
- OpenAI-compatible API for LLMs

**Asya🎭 value-add**:
- **Problem KServe solves**: Model serving, versioning, traffic splitting
- **Problem Asya🎭 solves**: Async request queuing, batch processing, workflow orchestration
- **Combined value**: KServe handles model lifecycle → Asya🎭 adds queue-based workflow

**Integration pattern**:

```yaml
# KServe InferenceService
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: sentiment-classifier
spec:
  predictor:
    containers:
    - name: kserve-container
      image: pytorch/torchserve:latest-gpu

---
# Asya🎭 binding
apiVersion: asya.sh/v1alpha1
kind: AsyaBinding
metadata:
  name: sentiment-async
spec:
  workloadRef:
    kind: Deployment
    name: sentiment-classifier-predictor  # Created by KServe
  transport:
    name: sqs
```

**Use case**:

Async ML pipeline: Upload video → SQS → Frame extraction (Asya🎭) → Object detection (KServe+Asya🎭) → Classification (KServe+Asya🎭) → Results

---

### Tier 2: High Value Integrations

#### 4. Volcano (Batch Scheduling)

**Priority**: ⭐⭐⭐⭐

**What it does**:
- CNCF batch scheduling system for K8s
- Gang scheduling (all-or-nothing job scheduling)
- Queue management with priority and fair-share
- Designed for AI/ML, big data, HPC workloads

**Asya🎭 value-add**:
- **Problem Volcano solves**: Resource scheduling, gang scheduling for distributed jobs
- **Problem Asya🎭 solves**: Message-driven triggering, async workflow coordination
- **Combined value**: Volcano schedules batch jobs → Asya🎭 triggers them via messages

**Integration pattern**:

```yaml
# Volcano Job triggered by Asya🎭
apiVersion: batch.volcano.sh/v1alpha1
kind: Job
metadata:
  name: distributed-training
spec:
  schedulerName: volcano
  minAvailable: 4  # Gang scheduling: need all 4 workers
  tasks:
  - replicas: 4
    template:
      spec:
        containers:
        - name: trainer
          image: pytorch-training:latest

---
# Asya🎭 actor triggers Volcano job via K8s API
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: training-orchestrator
spec:
  transport: rabbitmq
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          image: job-launcher:latest
          env:
          - name: ASYA_HANDLER
            value: "launcher.trigger_volcano_job"
```

**Use case**:

On-demand training: Message arrives → Asya🎭 triggers Volcano job → Gang-scheduled training → Results to S3 → Asya🎭 notifies completion

---

#### 5. Kueue (Job Queuing)

**Priority**: ⭐⭐⭐⭐

**What it does**:
- K8s-native job queuing and resource quotas
- Works with default K8s scheduler (not replacement)
- Multi-cluster job dispatching (MultiKueue)
- Priority scheduling, quota management

**Asya🎭 value-add**:
- **Problem Kueue solves**: Fair resource sharing, job admission control
- **Problem Asya🎭 solves**: External message queuing, async triggers, workflow routing
- **Combined value**: Asya🎭 routes messages → Kueue manages job quotas → Jobs execute

**Integration pattern**:

```yaml
# Kueue manages job quotas
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata:
  name: inference-queue
spec:
  clusterQueue: gpu-cluster-queue

---
# Asya🎭 actor submits jobs to Kueue-managed queue
apiVersion: batch/v1
kind: Job
metadata:
  name: inference-job
  labels:
    kueue.x-k8s.io/queue-name: inference-queue
spec:
  template:
    spec:
      containers:
      - name: inference
        image: model-inference:latest
```

**Use case**:

Multi-tenant inference: Different teams → Asya🎭 routes by tenant → Kueue enforces quotas → Jobs run within limits

---

#### 6. NVIDIA Triton Inference Server

**Priority**: ⭐⭐⭐⭐

**What it does**:
- High-performance inference server for GPUs
- Multi-framework (TensorFlow, PyTorch, ONNX, TensorRT)
- Dynamic batching, model ensembles
- Optimized for GPU utilization

**Asya🎭 value-add**:
- **Problem Triton solves**: GPU-optimized inference, dynamic batching
- **Problem Asya🎭 solves**: Request queuing, workflow orchestration, scale-to-zero
- **Combined value**: Triton handles GPU inference → Asya🎭 manages async workload flow

**Integration pattern**:

```yaml
# Triton Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: triton-server
spec:
  template:
    spec:
      containers:
      - name: triton
        image: nvcr.io/nvidia/tritonserver:25.01-py3
        args: ["tritonserver", "--model-repository=/models"]

---
# Asya🎭 binding
apiVersion: asya.sh/v1alpha1
kind: AsyaBinding
metadata:
  name: triton-async
spec:
  workloadRef:
    kind: Deployment
    name: triton-server
  transport:
    name: sqs
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: 20
```

**Use case**:

Batch inference: Files uploaded → S3 event → SQS → Asya🎭 → Triton (GPU batch inference) → Results

---

### Tier 3: Medium Value Integrations

#### 7. Seldon Core

**Priority**: ⭐⭐⭐

**What it does**:
- MLOps platform for K8s
- Model graphs (chaining, A/B testing, transformers)
- Custom CRD: SeldonDeployment
- Monitoring, explainability

**Asya🎭 value-add**:
- **Overlap**: Both support model chaining
- **Differentiation**: Seldon is synchronous REST/gRPC, Asya🎭 is async message-based
- **Combined value**: Seldon handles sync inference → Asya🎭 handles async batch processing

**Integration**: Similar to KServe pattern

---

#### 8. vLLM (LLM Inference Engine)

**Priority**: ⭐⭐⭐

**What it does**:
- Fast LLM inference with PagedAttention
- OpenAI-compatible API
- Continuous batching, tensor parallelism
- Often deployed via KServe or Ray Serve

**Asya🎭 value-add**:
- **Problem vLLM solves**: Fast LLM inference
- **Problem Asya🎭 solves**: Queue management, async request routing
- **Combined value**: vLLM handles inference → Asya🎭 handles batching from queue

**Integration**: Same as KServe/Ray pattern (vLLM deployed inside)

---

#### 9. BentoML + Yatai

**Priority**: ⭐⭐⭐

**What it does**:
- Model serving framework (Python-native)
- Yatai: K8s deployment platform (BentoDeployment CRD)
- Good for small teams, simple deployments

**Asya🎭 value-add**:
- **Problem BentoML solves**: Easy model packaging and serving
- **Problem Asya🎭 solves**: Enterprise-grade async workflows
- **Combined value**: BentoML simplifies deployment → Asya🎭 adds async layer

**Integration**: Similar to binding pattern

---

#### 10. llm-d (Distributed LLM Inference)

**Priority**: ⭐⭐⭐

**What it does**:
- K8s-native distributed inference stack
- KV-cache aware routing
- Disaggregated serving
- Modular, high-performance

**Asya🎭 value-add**:
- **Problem llm-d solves**: Multi-node LLM inference
- **Problem Asya🎭 solves**: Request queuing, workflow orchestration
- **Combined value**: llm-d handles distributed inference → Asya🎭 routes requests

**Integration**: Binding pattern to llm-d deployment

---

### Tier 4: Specialized Integrations

#### 11. Kubeflow Training Operator

**Priority**: ⭐⭐

**What it does**:
- Runs distributed training jobs (TFJob, PyTorchJob, MXJob)
- Integrates with Volcano/Kueue for scheduling

**Asya🎭 value-add**:
- Trigger training jobs from messages
- Coordinate multi-stage training pipelines

---

#### 12. Mosec

**Priority**: ⭐⭐

**What it does**:
- High-performance Python model serving
- Dynamic batching, multi-stage pipelines
- GPU-friendly

**Asya🎭 value-add**:
- Add async queuing layer
- Scale-to-zero capabilities

---

## Summary Table: Integration Value Matrix

| Tool    | Category            | KAITO Use Case         | Asya🎭 Value-Add              | Integration Complexity | Priority |
|---------|---------------------|------------------------|-----------------------------|------------------------|----------|
| KAITO   | Model Deployment    | ✅ Core (model mgmt)    | Async graphs, scale-to-zero | 🟢 Low                 | ⭐⭐⭐⭐⭐    |
| KubeRay | Distributed Compute | ✅ Multi-GPU inference  | External queuing, routing   | 🟡 Medium              | ⭐⭐⭐⭐⭐    |
| KServe  | Model Serving       | ✅ Production serving   | Async workflows             | 🟢 Low                 | ⭐⭐⭐⭐     |
| Volcano | Batch Scheduling    | Training orchestration | Message-driven jobs         | 🟡 Medium              | ⭐⭐⭐⭐     |
| Kueue   | Job Queuing         | Resource quotas        | External triggers           | 🟢 Low                 | ⭐⭐⭐⭐     |
| Triton  | GPU Inference       | GPU optimization       | Queue buffering             | 🟢 Low                 | ⭐⭐⭐⭐     |
| Seldon  | MLOps               | Model graphs           | Async batch                 | 🟡 Medium              | ⭐⭐⭐      |
| vLLM    | LLM Engine          | Fast inference         | Request queuing             | 🟢 Low                 | ⭐⭐⭐      |
| BentoML | Simple Serving      | Easy deployment        | Enterprise async            | 🟢 Low                 | ⭐⭐⭐      |
| llm-d   | Distributed LLM     | Multi-node LLM         | Workflow routing            | 🟡 Medium              | ⭐⭐⭐      |
