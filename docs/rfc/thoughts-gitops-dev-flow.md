### RFC: Dual-Mode Deployment Strategy for Asya

**Status:** Draft
**Date:** 2026-02-05
**Topic:** Bridging the gap between Data Scientist experimentation and GitOps production standards.

---

### 1. Problem Statement

**Asya** must serve two distinct user needs:

1. **Data Science Agility:** Instant, imperative deployment of AI actors via CLI/UI for rapid iteration.
2. **Production Stability:** Declarative, reproducible deployments managed by GitOps controllers (FluxCD/ArgoCD).

A strict "GitOps-only" approach introduces unacceptable latency for experimentation. Conversely, an "Imperative-only" approach creates "shadow IT" without audit trails. We need a unified architecture that supports imperative experimentation while providing a frictionless path to declarative production.

### 2. Proposed Solution: The "Imperative-to-GitOps" Promotion Workflow

We will implement a workflow that treats **Imperative Creation** and **GitOps Management** as sequential stages of the actor lifecycle, bridged by a robust `export` utility.

#### 2.1. The Workflow

1. **Experiment (Imperative):** The user deploys an actor via CLI/UI (`asya run ...`). `asya-stagedoor` talks directly to the Kubernetes API for instant feedback.
2. **Refine:** The user tests the actors, modifies parameters (memory, model version) imperatively until satisfied.
3. **Promote (Declarative):** The user runs `asya export <actor-id>`. The tool generates a clean, sanitized YAML manifest.
4. **Commit:** The user saves this manifest to their Git repository. The GitOps controller (Flux/Argo) then syncs this state to the production cluster/namespace.

#### 2.2. Supporting Infrastructure Patterns

To support the "Experiment" phase (Step 1), `asya-stagedoor` will support two configuration modes depending on the cluster's administrative policy:

* **Mode A: Namespace Isolation (Simpler UX)**
* *Concept:* Specific namespaces (e.g., `sandbox-*`) are unmanaged by GitOps.
* *Behavior:* `asya-stagedoor` or users themselves (via kubectl) deploy freely into these namespaces. Promotion involves exporting the YAML and committing it to a path monitored by Flux for a *different* (production) namespace.
* *Pros:* Zero risk of GitOps fighting `asya-stagedoor`; clear separation of concerns.
* *Cons:* Asya must explicitly support interactions between actors in different namespaces, so that to test newly developed actors with existing staging actors living in GitOps.

* **Mode B: Hybrid Namespace (via Labels)**
* *Concept:* Users experiment directly in staging namespaces that have some (older) workloads already running in GitOps, and then need flexibility editing them or adding new ones and testing
* *Behavior:* `asya-stagedoor` applies specific annotations (e.g., `kustomize.toolkit.fluxcd.io/prune: disabled` or `argocd.argoproj.io/sync-options: Prune=false` for Argo) to prevent the GitOps controller from deleting/rolling back the imperative resource.
* *Pros:* Useful when resources must sit side-by-side (e.g., connecting to staging DBs), but requires careful label management.
* *Cons:* Complex collaboration of multiple users.


### 3. Key Technical Deliverable: The Sanitizer

See appendix section for Weak points below.

To make Step 3 ("Promote") viable, the `export` function must be more than a simple `kubectl get`. It must act as a **Smart Sanitizer**:

* **Strip Metadata:** Remove `uid`, `resourceVersion`, `managedFields`, and `status`.
* **Remove Guardrails:** Strip the `prune: disabled` labels so the GitOps controller can take full ownership.
* **Redact Secrets:** Ensure no sensitive data is dumped to plain text.
* **Abstract:** Collapse complex internal specs into readable "Flavors" (e.g., `flavor: gpu-large`).

### 4. Alternatives Considered

* **Asya Stagedoor as Git Client (Rejected):**
* *Concept:* The HTTP Asya Stagedoor handles `git commit/push` internally.
* *Reason for Rejection:* Introduces high complexity (conflict resolution, authentication management) and forces "CI latency" onto the experimentation phase. `asya-stagedoor` should remain stateless.


----
# Appendix - Thoughts on Weak Spots

You are essentially building a **"ClickOps to GitOps"** bridge. This is a very standard pattern in mature internal developer platforms (IDPs).

By keeping the Gateway stateless and placing the "commit" responsibility on the user, you remove 90% of the complexity (auth, git merge logic, state management) from your tool.

Here is an analysis of the weak spots you need to handle in your "Export" logic to make this smooth.

### Weak Spot 1: The "Secret" Trap

This is the biggest technical hurdle.

* **Scenario:** A user launches an actor imperatively with an API key: `asya run --env OPENAI_KEY=sk-123...`.
* **The Problem:** When they "Export" the YAML from K8s, that secret is inside a Kubernetes Secret object (base64 encoded).
* **The Risk:** If the user commits that raw YAML to Git, **they have just committed a plain-text credential.** (Base64 is not encryption).
* **The Fix:**
* Your "Export" function must **redact** sensitive values or Reference objects.
* Ideally, your CRD should support `secretRef` or `externalSecrets`.
* **UX:** The export output should comment out the secret section and add a clear TODO: `# TODO: Add your secret securely (e.g., SealedSecret or Vault)`



### Weak Spot 2: "Flavor" Abstraction Leaks

You mentioned using "Flavors" to keep YAMLs simple. You need to decide *where* that flavor is processed.

* **Scenario:** User selects "Flavor: GPU-Large". This translates to specific tolerations, node affinities, and resource limits.
* **Weak Implementation (Client-side expansion):** The Gateway expands "GPU-Large" into 50 lines of Pod spec and sends that to K8s. When the user exports the YAML, they get the 50 lines of mess, not the word "GPU-Large".
* **Strong Implementation (Server-side expansion):** Your CRD has a field `spec.flavor: gpu-large`. The Gateway sends just that. The K8s Controller (operator) reads that and modifies the Pod on the fly.
* **Benefit:** The exported YAML remains tiny and readable (`flavor: gpu-large`), maintaining your "DS-oriented" promise.

### Weak Spot 3: Stripping "Operational Metadata"

When you `kubectl get -o yaml`, Kubernetes adds a lot of noise that should **never** go into Git.

* **The Noise:** `managedFields`, `resourceVersion`, `uid`, `creationTimestamp`, `status` block, and your specific `prune: disabled` annotation.
* **The Weak Spot:** If a user commits `uid` or `resourceVersion`, the Flux apply will fail because those fields are immutable/server-generated.
* **The Fix:** Your download/export logic implies a "Cleaner" function. It must aggressively strip:
1. All `status:` fields.
2. All `metadata:` fields except `name`, `namespace`, and `labels`.
3. **Crucially:** It must strip the `kustomize.toolkit.fluxcd.io/prune: disabled` annotation.


* *Why?* If you commit `prune: disabled` to Git, Flux will never be able to delete that actor when the user removes it from Git later. You want Flux to "claim" ownership by applying a manifest *without* that annotation.



### Weak Spot 4: Namespace Collisions

* **Scenario:** User creates `actor-1` in namespace `default` via UI. They export it. They edit the YAML to deploy to namespace `prod`.
* **The Weak Spot:** Imperative users tend to be sloppy with namespaces.
* **The Fix:** Ensure the exported YAML explicitly includes `namespace: <current-ns>` OR deliberately excludes it so it depends on where Flux applies it. Explicit is usually safer for GitOps.

### Summary Checklist for your "Export" Feature

To make this "Hybrid" approach work, your Export logic is the critical component. It should not just be a `kubectl get -o yaml`. It needs to be a **Sanitizer**:

1. **Redact Secrets:** Never output base64 data to the user download.
2. **Preserve Intent:** Keep high-level abstractions (Flavors) rather than expanded specs.
3. **Clean Metadata:** Remove `uid`, `resourceVersion`, `status`, and `managedFields`.
4. **Remove Safety Labels:** Strip the `prune: disabled` annotation so GitOps can take full ownership upon the first sync.
