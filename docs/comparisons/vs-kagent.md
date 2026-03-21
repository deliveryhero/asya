# Asya vs KAgent

## TL;DR

KAgent and Asya are both Kubernetes-native but solve different problems.
KAgent gives you **CRDs for defining AI agents** -- an Agent resource wraps a
system prompt, LLM config, and MCP tool servers, then a controller runs the
agent via Google ADK. Asya gives you **CRDs for composing AI workloads** --
an AsyncActor resource declares a stateless handler that processes messages
from a queue, scales independently via KEDA, and routes envelopes to the next
actor in the mesh. KAgent is agent-centric; Asya is pipeline-centric.

## At a Glance

| | 🎭 | KAgent |
|---|---|---|
| **One-liner** | Actor mesh for AI workloads on Kubernetes | Kubernetes-native AI agent management |
| **Core abstraction** | AsyncActor (stateless handler + queue + sidecar) | Agent (system prompt + tools + LLM config) |
| **Execution model** | Choreography: envelope carries the route through a mesh of actors | Controller: operator provisions and runs agents via Google ADK engine |
| **Communication** | Async message queues (SQS, RabbitMQ, GCP Pub/Sub) | Synchronous request/response via ADK |
| **Scaling** | ✅ Per-actor via KEDA (queue depth), scale-to-zero | ❌ No built-in autoscaling; agents run as controller-managed processes |
| **Multi-step pipelines** | ✅ Native: route chains actors, Flow DSL compiles Python to actor graphs | ❌ Not a pipeline framework; agents call tools, not other agents in a mesh |
| **Handler format** | ✅ Plain `dict -> dict` Python function, no SDK | ⚠️ Agent defined as YAML CRD; execution handled by ADK engine |
| **Tool integration** | Agents are actors; tools are other actors or external calls | MCP ToolServer CRDs with built-in K8s, Istio, Helm, Argo, Prometheus tools |
| **LLM providers** | BYO -- handler calls any LLM SDK directly | Declarative ModelConfig CRD (OpenAI, Anthropic, Vertex AI, Ollama) |
| **Observability** | Envelope trace_id across actor logs; KEDA metrics | OpenTelemetry tracing built-in |
| **UI** | CLI (`asya flow`, `asya mcp`) | Web UI for agent and tool management |
| **Primary use case** | Multi-step AI/ML pipelines, agentic workflows at scale | Single-agent K8s operations (troubleshooting, monitoring, infra management) |
| **Maturity** | 🟡 Alpha (production at Delivery Hero) | 🟡 Early (CNCF Sandbox, pre-v1) |

## Architecture

### KAgent

KAgent follows the **Kubernetes operator pattern**. A controller watches three
CRDs -- `Agent`, `ModelConfig`, and `ToolServer` -- and provisions the
infrastructure needed to run agents. The execution engine is Google's ADK
(Agent Development Kit). When an agent is invoked, the engine loads the system
prompt, connects to the configured LLM provider, and makes tools available
from registered MCP servers.

```
User/UI ──> KAgent Engine (ADK) ──> LLM Provider
                  │                      │
                  ├── ToolServer (K8s)    │
                  ├── ToolServer (Helm)   │
                  └── ToolServer (Istio)  │
                                         ▼
                                    Response
```

KAgent excels at **single-agent operational tasks**: a platform engineer
defines an agent that can inspect Kubernetes resources, query Prometheus, and
manage Helm releases -- all through declarative YAML.

### Asya

Asya uses **choreography** instead of a central controller. Each actor is an
independent pod with a Go sidecar that handles queue I/O, retries, and
envelope routing. Messages carry their own route (`prev/curr/next`), so actors
do not need to know about each other. Crossplane Compositions render the full
pod spec from the AsyncActor CRD.

```
Queue A ──> Actor A ──> Queue B ──> Actor B ──> Queue C ──> Actor C ──> x-sink
            (0-20)                  (0-5 GPU)               (0-10)
```

Each actor scales independently based on its own queue depth. GPU actors scale
0-5 while CPU actors scale 0-50. An optional HTTP gateway exposes the mesh
via A2A and MCP protocols.

## Developer Experience

### KAgent: define an agent

```yaml
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: k8s-troubleshooter
spec:
  systemPrompt: |
    You are a Kubernetes troubleshooting assistant.
    Diagnose pod failures and suggest fixes.
  modelConfigRef:
    name: gpt-4o-config
  toolServers:
    - name: kubernetes-tools
    - name: prometheus-tools
```

The controller handles LLM calls, tool dispatch, and conversation management.
The developer writes YAML, not code.

### Asya: define an actor pipeline

```python
# handler.py -- plain Python, no SDK
def diagnose(state: dict) -> dict:
    state["diagnosis"] = analyze_pod_logs(state["pod"])
    return state

def recommend(state: dict) -> dict:
    state["fix"] = llm.generate(state["diagnosis"])
    return state
```

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: diagnose
spec:
  handler: handler.diagnose
  scaling:
    minReplicaCount: 0
    maxReplicaCount: 10
  resiliency:
    actorTimeout: 120s
    policies:
      default:
        maxAttempts: 3
        backoff: exponential
```

Actors are composed into pipelines via envelope routing or the Flow DSL.
The developer writes Python functions and Kubernetes manifests.

## When to Choose KAgent

KAgent is the simpler choice when:

- **Single-agent K8s operations** -- you want an AI assistant that queries
  your cluster, checks Prometheus alerts, or manages Helm releases. KAgent's
  built-in MCP tool servers for K8s, Istio, Argo, and Grafana cover this
  out of the box.
- **Declarative agent definition** -- you want to define agents entirely in
  YAML without writing handler code. KAgent's Agent CRD wraps system prompt,
  LLM config, and tool references into a single resource.
- **Managed LLM configuration** -- ModelConfig CRDs let you switch between
  OpenAI, Anthropic, Vertex AI, and Ollama without changing agent code.
- **Web UI for agent management** -- KAgent ships a UI for creating and
  testing agents interactively.
- **CNCF ecosystem alignment** -- as a CNCF Sandbox project, KAgent has
  community governance and a standardized contribution model.

## When to Choose Asya

Asya is purpose-built for multi-step AI workloads at scale:

- **Multi-actor pipelines** -- preprocessing, LLM inference, postprocessing,
  and evaluation as independent actors with per-step scaling and failure
  isolation. KAgent runs single agents, not pipelines.
- **Scale-to-zero GPU workloads** -- KEDA scales each actor independently
  based on queue depth. GPU pods cost nothing between batches.
- **Dynamic routing** -- actors rewrite `route.next` at runtime. An LLM
  judge routes high-confidence results to storage and low-confidence results
  to human review. KAgent has no inter-agent routing.
- **Agentic patterns at scale** -- pause/resume for human-in-the-loop, FLY
  streaming for live token output, fan-out/fan-in via the Flow DSL. These
  patterns run as distributed actor graphs, not single-process agents.
- **Transport flexibility** -- SQS, RabbitMQ, or GCP Pub/Sub as the message
  backbone. Swap transports without changing handler code.
- **No execution engine lock-in** -- handlers are plain Python functions.
  Call any LLM SDK, any tool library, any framework. KAgent is coupled to
  Google ADK for agent execution.
