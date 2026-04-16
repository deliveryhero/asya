---
description: "Comparison: Asya vs KServe, KAITO, KubeAI, vLLM, LLM-d — AI/ML model serving"
---

# AI/ML Serving

**KServe, KAITO, KubeAI, vLLM/SGLang, LLM-d**

## TL;DR

Model serving tools provide **inference endpoints** — they load a model into GPU memory, handle
batching, and expose a predict/completions API. Asya is the **pipeline layer** that connects
these endpoints into multi-step workflows with queue-based routing and independent scaling.
An Asya actor calls a KServe or vLLM endpoint; it does not replace one.

## Comparison Table

| Dimension | KServe | KAITO | KubeAI | vLLM / SGLang | LLM-d | 🎭 |
|---|---|---|---|---|---|---|
| **Primary purpose** | Model serving on K8s with autoscaling | One-click LLM deployment on AKS | Lightweight LLM gateway on K8s | High-throughput LLM inference engine | Disaggregated LLM serving for K8s | Multi-step AI pipeline routing |
| **What it deploys** | InferenceService CRD (predictor + transformer + explainer) | GPU node provisioning + model deployment via Workspace CRD | Model CRD with OpenAI-compatible endpoint | Single inference server process | Prefill/decode disaggregated serving pods | AsyncActor CRD (stateless pod + sidecar + queue) |
| **Scaling trigger** | Knative (RPS/concurrency) or HPA | Azure node autoprovisioner | Pending request count | N/A (single process, external LB) | KPA or custom metrics | KEDA (queue depth per actor) |
| **Scale to zero** | ✅ Yes (Knative serverless) | ❌ No (GPU nodes stay provisioned) | ✅ Yes (based on pending requests) | ❌ No (process must be running) | ⚠️ Depends on autoscaler config | ✅ Yes (per actor, per queue) |
| **GPU management** | Tolerations + node selectors | Provisions GPU nodes automatically (Azure) | Node selectors, multi-GPU | Direct CUDA access, tensor parallelism | Disaggregated prefill/decode across GPUs | Delegates to K8s scheduler; actors specify resource requests |
| **Batching** | Built-in request batching | Inherited from inference runtime | Proxy-level batching | Continuous batching, PagedAttention | Continuous batching with KV-cache routing | No batching (one envelope = one invocation) |
| **Protocol** | REST/gRPC (V1/V2 inference protocol) | OpenAI-compatible API | OpenAI-compatible API | OpenAI-compatible API | OpenAI-compatible API | Envelope protocol over message queues |
| **Multi-step pipelines** | ⚠️ Transformer chain (limited, same InferenceService) | ❌ No | ❌ No | ❌ No | ❌ No | ✅ Core capability: actors chained via queue routing |
| **Dynamic routing** | ❌ No | ❌ No | ❌ No | ❌ No | ⚠️ Routing between prefill/decode nodes | ✅ Actors rewrite `route.next` at runtime |
| **Supported models** | Any (custom containers) | Curated catalog (Llama, Mistral, Falcon, etc.) | Curated catalog (Ollama, vLLM backends) | Any HuggingFace-compatible LLM | LLMs via vLLM backend | Any workload (LLM, vision, audio, custom code) |
| **Queue integration** | ❌ No (synchronous request/response) | ❌ No | ❌ No | ❌ No | ⚠️ NATS-based internal routing | ✅ Native: SQS, RabbitMQ, GCP Pub/Sub |

## When to Use What

**Use KServe / KAITO / KubeAI / vLLM / LLM-d when:**

- You need a **model inference endpoint** — load a model, expose a predict or completions API
- Your concern is **serving throughput** — continuous batching, PagedAttention, tensor parallelism
- You want **managed model lifecycle** — canary rollouts, A/B testing, model versioning
- You need an **OpenAI-compatible API** for drop-in replacement of hosted LLM providers

**Use Asya when:**

- You need to **chain multiple steps** — preprocess, call an LLM endpoint, postprocess, score, route
- Steps have **different scaling profiles** — a CPU formatter at 50 replicas feeding a GPU scorer at 3
- You want **queue-based decoupling** — callers enqueue and move on; no connection held open during inference
- You need **dynamic routing** — an LLM judge routes high-confidence results to storage, low-confidence to human review
- Your pipeline mixes **multiple model endpoints** (KServe for vision, vLLM for text) into a single workflow
