---
title: Research compatibility with Kro
priority: 2 # medium
reason: research done
---
# Research results:

kro vs Crossplane for Asya: Analysis

How Crossplane Is Used Today

Asya uses Crossplane as its core deployment engine — replacing a custom Kubernetes operator. The AsyncActor CRD (via XRD) lets users
declare an actor, and Crossplane compositions render the full pod spec (runtime container + sidecar + state proxies + volumes),
provision transport queues (SQS, Pub/Sub), and wire up KEDA autoscaling.

Key stats:
- ~3,250 lines of Crossplane-specific code (compositions + custom function)
- 3 compositions (SQS, RabbitMQ, Pub/Sub) with 60-70% duplication
- Pipeline mode with function-go-templating (405 Go template expressions in the SQS composition alone)
- Custom function (function-asya-flavors, 980 lines Go) for type-aware merging of EnvironmentConfigs
- 3 providers: provider-kubernetes, provider-aws-sqs, provider-gcp-pubsub

★ Insight ─────────────────────────────────────
Asya's Crossplane usage is unusually sophisticated — most Crossplane users compose cloud resources with simple patches. Asya instead
uses compositions for inline sidecar injection (rendering full pod specs with Go templates), which pushes Crossplane far beyond its
typical use case. This is where much of the template complexity comes from.
─────────────────────────────────────────────────

---
What kro Offers

kro (Kube Resource Orchestrator) is a Kubernetes SIG subproject backed by Google, AWS, and Microsoft. It lets you define a
ResourceGraphDefinition (RGD) that dynamically creates a CRD and a dedicated controller. Resources are templated with CEL expressions
and dependencies are automatically inferred from expression references.

┌───────────────────┬─────────────────────────────────────────┬────────────────────────────────────────┐
│      Aspect       │          Crossplane (current)           │                  kro                   │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ Maturity          │ Production-ready, CNCF graduated        │ Alpha (v1alpha1), not production-ready │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ API surface       │ XRD + Composition (dual CRD)            │ Single CRD: ResourceGraphDefinition    │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ Templating        │ Go templates (verbose, 405 expressions) │ CEL expressions (concise, type-safe)   │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ Cloud resources   │ Built-in providers (SQS, Pub/Sub)       │ Requires separate ACK/KCC/ASO          │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ Composition reuse │ No inheritance, must duplicate          │ Same — no composition inheritance      │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ Custom functions  │ Yes (function-asya-flavors)             │ No extension mechanism                 │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ Schema definition │ OpenAPI (verbose)                       │ SimpleSchema (concise)                 │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ Scope             │ Cluster-scoped                          │ Namespace-scoped                       │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ Controller model  │ Single controller for all compositions  │ One microcontroller per RGD            │
├───────────────────┼─────────────────────────────────────────┼────────────────────────────────────────┤
│ Security model    │ Arbitrary code in functions             │ CEL-only (non-Turing-complete)         │
└───────────────────┴─────────────────────────────────────────┴────────────────────────────────────────┘

---
Would kro Work for Asya?

Let me evaluate against Asya's specific requirements:

1. Cloud Resource Provisioning (SQS queues, Pub/Sub topics)

Crossplane: Built-in. provider-aws-sqs creates queues, provider-gcp-pubsub creates topics/subscriptions — all managed as part of the
composition pipeline.

kro: Would need ACK (AWS Controllers for Kubernetes) and KCC (Config Connector) installed separately. kro can then orchestrate their
CRDs. This is functionally equivalent but adds operational overhead — you're now running ACK + KCC + kro instead of just Crossplane.

Verdict: Crossplane wins on operational simplicity for multi-cloud.

2. Complex Pod Spec Rendering (Sidecar Injection)

This is Asya's most complex composition task — rendering a Deployment with runtime container, asya-sidecar, optional state proxy
containers, volume mounts, env vars from resiliency policies, etc.

Crossplane: Uses Go templates — verbose but Turing-complete. Can handle any logic.

kro: Uses CEL — concise and type-safe, but non-Turing-complete. CEL supports conditionals, string manipulation, and list operations,
but complex container spec construction (iterating over stateProxy[] to generate sidecar containers, conditional volume mounts,
JSON-encoding resiliency policies) would be significantly harder or impossible in CEL.

Verdict: Crossplane's Go templates are painful but capable. CEL may hit walls on Asya's pod spec complexity.

3. Flavor Resolution (EnvironmentConfig Merging)

Asya's function-asya-flavors fetches a variable-length list of EnvironmentConfigs, merges them with type-aware semantics (lists
append, maps merge, scalars conflict-detect), then overlays the actor's inline spec.

kro: Has no equivalent mechanism. ExternalRef can reference existing resources, but there's no type-aware merge, no dynamic list of
references, and no function extension point. You'd need to implement this outside kro entirely.

Verdict: Crossplane wins — custom functions are a major extensibility advantage.

4. Status Derivation

Asya derives actor phase (Creating/Ready/Napping) from the combined readiness of queue, KEDA ScaledObject, and Deployment.

kro: Supports status projection via CEL expressions that reference composed resource statuses. This could potentially work:
${deployment.status.readyReplicas > 0 && queue.status.ready == true ? "Ready" : "Creating"}. kro's CEL-based approach might actually
be cleaner than Asya's current Go template status pipeline.

Verdict: kro has a slight edge for status derivation — CEL is more readable than Go templates for this.

5. Composition Duplication

60-70% of Asya's composition logic is identical across SQS/RabbitMQ/Pub/Sub. Neither Crossplane nor kro supports composition
inheritance or parameterization.

Verdict: Tie — both suffer from the same limitation.

---
The Blockers

Three issues make kro not viable for Asya today:

1. Alpha maturity — v1alpha1 API with breaking changes expected. Asya runs production workloads on K8s; swapping the deployment
engine to an alpha project is high-risk.
2. No extension mechanism — kro has no equivalent to Crossplane functions. function-asya-flavors (type-aware flavor merging) is a
core Asya feature that can't be replicated in kro.
3. CEL limitations for complex pod specs — Asya's sidecar injection involves iterating over variable-length lists, conditional
container generation, JSON encoding, and nested map construction. CEL's non-Turing-completeness could block this.

---
Where kro Could Be Interesting

Despite the blockers, kro has appealing properties for a future evaluation:

- SimpleSchema is dramatically less verbose than OpenAPI for XRD definitions (Asya's XRD is 469 lines)
- CEL is more readable than Go templates for straightforward field mapping
- Automatic dependency resolution from expression references (no manual pipeline ordering)
- Namespace-scoped resources are a better fit for multi-tenant platforms
- SIG-backed with Google/AWS/Microsoft — likely to mature significantly

★ Insight ─────────────────────────────────────
The fundamental architectural difference: Crossplane is a platform for building platforms (extensible via providers and functions),
while kro is a composition engine (simpler but less extensible). Asya has pushed into the "platform" territory by building a custom
function (function-asya-flavors), which firmly places it in Crossplane's sweet spot. If Asya's compositions were simpler (just wiring
CRDs together without custom merge logic), kro would be a much stronger contender.
─────────────────────────────────────────────────

---
Recommendation

Stay on Crossplane. The migration cost is high, the gain is marginal, and kro lacks the extensibility Asya needs (custom functions,
built-in cloud providers). Re-evaluate when kro reaches v1beta1+ and adds an extension mechanism.

However, consider tracking two kro features:
- forEach expansion — if it matures, could solve Asya's state proxy container iteration more cleanly
- Collection watching — on the v0.9.0 roadmap, could simplify status aggregation

If you want, I can file an aint to track kro maturity for a future re-evaluation, or dive deeper into any specific aspect of this
comparison.