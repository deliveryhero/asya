## RFC: Transitioning Asya.sh to a Crossplane + Mutating Webhook Architecture

---

### 1. Objective

To evolve `asya.sh` from a bespoke, imperative operator into a declarative, cloud-native control plane. By leveraging **Crossplane** https://www.crossplane.io/ for infrastructure/resource orchestration and a **Mutating Webhook** for workload injection, we aim to increase stability, reduce maintenance overhead, and provide built-in drift detection.

### 2. Current State vs. Proposed State

#### **The Problem (Current)**

* **Maintenance Burden:** The `asya-operator` manually manages the lifecycle of SQS/RabbitMQ, KEDA, and Deployments via Go code.
* **Race Conditions:** Patching deployments after creation causes pod restarts and sync-fights with GitOps tools (ArgoCD/Flux).
* **Drift Ignorance:** If an external resource (like an SQS queue) is modified manually, the operator does not automatically revert it unless the CR changes (or it's very hard to implement and barely works).

#### **The Solution (Proposed)**

* **Crossplane (Infra):** Use Crossplane **Compositions** to define the "What" (Queue + KEDA + IAM).
* **Mutating Webhook (Injection):** Use a lightweight webhook to handle the "How" (Sidecar injection + Env vars).

---

### 3. Proposed Architecture

#### **A. The New API (XRD)**

The `AsyncActor` CRD will be replaced by a Crossplane **CompositeResourceDefinition (XRD)**. This defines the schema for users while keeping the implementation details abstracted.

```yaml
# Simplified XRD Spec
spec:
  transport: "sqs" | "rabbitmq"
  workload: object (Optional) - "template", full definition
  workloadRef: string (Optional) - alternative
  scaling:  # keda setup
    enabled: true
    minReplicas: int
    maxReplicas: int

```

#### **B. The Implementation (Composition)**

A Crossplane **Composition** will map the `AsyncActor` spec to multiple underlying resources:

1. **Cloud Resource:** (e.g., `queue.aws.upbound.io`) for the message broker.
2. **KEDA Resource:** (`scaledobjects.keda.sh`) to manage autoscaling.
3. **App Resource:** (Optional) If `workload` is provided, a `deployment.apps` is managed via `provider-kubernetes`.

#### **C. The Injector (Mutating Webhook)**

A single Go-based webhook will watch for Pod creation. If the Pod belongs to a Deployment associated with an `AsyncActor` (identified via labels `asya.sh/inject: "true"`), it will:

* Inject the `asya-sidecar` container.
* Mount asya_runtime.py
* Inject connection strings/secrets as Environment Variables.
* think of other operations currently performed by `asya-operator` to be done by the injector

Q: How would we call this package: `asya-injector` or `asya-webhook`?

---

### 4. Comparison of Workflows

| Scenario | Path A: New Deployment | Path B: Existing Deployment |
| --- | --- | --- |
| **User Action** | Define `AsyncActor` with `workload`. | Define `AsyncActor` with `workload`. |
| **Crossplane** | Creates SQS + KEDA + Deployment. | Creates SQS + KEDA (targeting existing Ref). |
| **Webhook** | Injects sidecar into Crossplane-created Pods. | Injects sidecar into User-managed Pods. |

---

### 5. Implementation Roadmap

1. **Phase 1: Foundation**
* Install Crossplane and required providers (`provider-aws`, `provider-kubernetes`).
* Define the `AsyncActor` XRD.

2. **Phase 2: The Injector**
* Extract sidecar injection logic from the current operator into a standalone Mutating Webhook.
* Deploy the webhook as a core component of the `asya-system` namespace.

3. **Phase 3: Compositions**
* Create the AWS SQS and RabbitMQ Compositions.
* Implement **Composition Functions** (Go) if complex logic (like dynamic IAM policy generation) is required -> needs more exploration.

4. **Phase 4: Cleanup**
* Migrate existing `asya-operator` logic to the new system -> no need to deprecate, we don't have active users yet, can just break things!.
* Decommission the old controller loop.

---

### 6. Expected Benefits

* **Stability:** Crossplane provides 24/7 drift correction for cloud infrastructure.
* **Scalability:** Adding support for GCP Pub/Sub or Azure Service Bus becomes a YAML configuration task rather than a coding project.
* **GitOps Friendly:** The Mutating Webhook ensures that the "Desired State" in Git matches the "Live State" without patching cycles.

---
Q: in case where `AsyncActor` uses and existing `workloadRef`, will injector inject pods into already running workloads?
A: The short answer is **no**, not automatically.
In Kubernetes, a Mutating Webhook is an **admission** controller. It only acts when the API server receives a request to **Create** or **Update** a resource. It cannot "reach back in time" to modify a Pod that is already running and has passed the admission phase.
However, there are standard patterns to handle this "day-zero" injection for existing workloads. Here is how it works and how you should handle it for `asya.sh`.
### 1. The Trigger: Pod Rotation
For the sidecar to be injected into an existing `StatefulSet` or `Deployment`, the Pods must be **re-created**.
* If you apply a new `AsyncActor` that points to an existing `StatefulSet`, nothing happens to the current Pods.
* As soon as you trigger a rollout (e.g., `kubectl rollout restart statefulset/my-app`), the new Pods will hit the Webhook, and the sidecar will be injected.
### 2. The "Automated Restart" Pattern
If you want `asya.sh` to feel truly seamless, your system needs a way to notify the workload that it needs to pick up the new "Actor" configuration. There are two common ways to handle this:
#### Option A: Manual (The "Safe" Way)
You document that after creating an `AsyncActor` for an existing workload, the user must perform a rollout. This is standard for tools like **Istio** or **Linkerd**.
#### Option B: The "Reloader" Pattern (The "Pro" Way)
Since you are using Crossplane, you can use a small controller (or a Crossplane Composition Function) that watches for changes to `AsyncActor` objects.
1. When an `AsyncActor` is created/updated, the controller looks at the `workloadRef`.
2. It adds or updates an **annotation** on the target Workload (e.g., `asya.sh/last-applied: <timestamp>`).
3. Kubernetes sees the change in the Workload's `podTemplateSpec` and automatically triggers a rolling update of the Pods.
4. The new Pods hit your **Mutating Webhook**, and the sidecar is injected.
### 3. Handling the "Chicken and Egg" Problem
There is a specific risk with `workloadRef`: **Race Conditions.**
If the user's Workload starts *before* the `AsyncActor` (and thus the SQS queue) is ready, the sidecar might crash because the SQS URL or Secrets it needs don't exist yet.
**How to solve this in your Webhook:**
Your Webhook should check if the referenced `AsyncActor` is **Ready** (Crossplane provides a `Ready` status on all managed resources).
* **If Ready:** Inject the sidecar and the env vars.
* **If Not Ready:** You can either:
1. **Reject the Pod creation** (with a "silently retry" error), forcing K8s to wait until the infra is ready.
2. **Inject a "Wait" Init-Container** that pings the `AsyncActor` status or waits for the Secret to appear.
### Summary of Behavior
| Event | Effect on Pods |
| --- | --- |
| **New `AsyncActor` created** | Existing Pods continue running (No sidecar). |
| **Pod dies / Node drains** | Replacement Pod gets sidecar injected. |
| **`kubectl rollout restart`** | All new Pods get sidecars injected. |
| **Workload Annotation Update** | Triggers rolling update  all Pods get sidecars. |
### Recommendation
For `asya.sh`, I suggest starting with **Option A** (Manual restart) for simplicity, but add a label-check in your Webhook. If a Pod is part of a `workloadRef` but doesn't have the sidecar yet, you can surface a warning in the `AsyncActor` status field: *"Status: Pending (Workload requires restart to inject sidecar)."*
==> Agree on option A because for now we need to focus on `workload` only, not on `workloadRef` - we don't have a strong use-case for `workloadRef` yet.
