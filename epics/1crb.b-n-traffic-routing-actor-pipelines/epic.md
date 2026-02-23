---
title: A/B/N Traffic Routing for Actor Pipelines
priority: 2 # medium
type: epic
---


This epic introduces a two-layer mechanism for A/B/N testing, canary routing, and traffic splitting in Asya actor pipelines. Layer 1 adds a minimal header-based route override to the sidecar (static name remapping via dictionary lookup), while Layer 2 provides Python-level router actors for probabilistic and conditional routing logic. Together, these layers fill a gap in the cloud-native ecosystem where no existing tool supports progressive delivery on message queues.

## RFC: A/B/N Traffic Routing for Actor Pipelines

### Abstract

This RFC proposes a two-layer mechanism for A/B/N testing, canary routing, and traffic splitting in Asya actor pipelines. Layer 1 adds a minimal header-based route override to the sidecar (static name remapping, one dictionary lookup). Layer 2 provides Python-level router actors for probabilistic and conditional routing logic (A/B weights, multi-armed bandit, fan-in sharding). Together, the two layers keep the message `route` field as pure business logic while handling traffic management as a non-functional concern via `headers`.

### Motivation

Data Scientists using Asya need to:

1. **A/B/N test** actor variants in production pipelines (e.g., compare `model-v1` vs `model-v2` with 90/10 traffic split)
2. **Route staging traffic** to a local or development actor for debugging (100% redirect)
3. **Canary deploy** a new actor version with gradual traffic increase
4. **Shard stateful fan-in actors** across N instances based on payload keys
5. **Run multi-armed bandit** experiments that dynamically shift traffic based on performance

Today, none of these are possible without manually creating separate pipelines with hardcoded route variants. There is no mechanism to split traffic at the actor level within a single pipeline.

#### Why Not Existing Tools?

No CNCF project or major open-source tool supports A/B testing on message queues:

| Project | Traffic Splitting? | Protocol |
|---------|-------------------|----------|
| Flagger (CNCF) | ✅ | HTTP/gRPC only |
| Argo Rollouts (CNCF) | ✅ | HTTP/gRPC only |
| Iter8 | ✅ | HTTP/gRPC only |
| Istio / Linkerd / Envoy | ✅ | L7 HTTP/gRPC only |
| Dapr (CNCF) | Content-based only | No percentage-based splitting |
| Knative Eventing (CNCF) | ❌ | Fan-out only, no weighted routing |

The entire progressive delivery ecosystem assumes HTTP traffic flowing through service meshes or ingress controllers. Message queues use consumer-pull, not proxy-intercept. No "proxy" exists to insert traffic splitting logic. This is genuinely unoccupied space in the cloud-native ecosystem.

The closest native mechanism is RabbitMQ's **Consistent Hash Exchange plugin**, which provides coarse-grained weighted distribution across queues. It was designed for load balancing, not controlled experimentation: the hash ring is in-memory only, distribution depends on routing key entropy, and it provides no experiment management, sticky sessions, or metrics.

(TODO: think more on whether similar design would be useful on asya-level, transport-agnostic)

### Design Principles

1. **Route = business logic.** The `route.actors` array describes what the pipeline does. A/B testing, sharding, and canary routing are non-functional concerns that belong in `headers`, not `route`.

2. **Sidecar stays simple.** The sidecar is a message router, not an experiment engine. It performs a dictionary lookup, not probability calculation or condition evaluation.

3. **Python is the condition language.** Data Scientists already write Python. All complex routing logic (probability, MAB, conditions, sharding) lives in Python where they can read, test, and extend it.

4. **Two tools, not one leaky abstraction.** Static override (deterministic, zero hops) and router actor (programmatic, one hop) serve different needs cleanly. No middle-ground "probability in headers" that is too limited for real experiments but too complex for simple overrides.

5. **Debuggability over latency.** For complex experiments, one extra queue hop is acceptable because Data Scientists need to see and understand what happened. The override header provides a clear audit trail. Hops are cheap - this is at a core of asya's design (if need less latency - use faster transport).

### Architecture

#### Two-Layer Design

```
Layer 1: Sidecar Route Override (static, deterministic)
+------------------------------------------------------------------+
|  Message headers contain:                                        |
|  "x-asya-route-override": {"model": "model-v2"}                 |
|                                                                  |
|  Sidecar at routing time:                                        |
|  - Looks up next actor name in override map                      |
|  - If found, routes to override target instead                   |
|  - If not found, routes normally                                 |
|  - Zero extra hops, zero probability logic                       |
+------------------------------------------------------------------+

Layer 2: Python Router Actors (programmatic, flexible)
+------------------------------------------------------------------+
|  Router actor in pipeline:                                       |
|  - Reads experiment config (env, ConfigMap, external service)    |
|  - Makes routing decision (weighted random, MAB, hash, etc.)     |
|  - Stamps x-asya-route-override header for downstream sidecar    |
|  - One extra queue hop per experiment point                      |
+------------------------------------------------------------------+
```

#### Message Protocol Extension

Current message structure (unchanged fields omitted):

```json
{
  "route": {"actors": ["prep", "model", "post"], "current": 0},
  "headers": {
    "trace_id": "abc-123"
  },
  "payload": {}
}
```

With route override:

```json
{
  "route": {"actors": ["prep", "model", "post"], "current": 0},
  "headers": {
    "trace_id": "abc-123",
    "x-asya-route-override": {
      "model": "model-v2"
    }
  },
  "payload": {}
}
```

The `x-asya-route-override` header is a flat map of `{logical-actor-name: target-logical-actor-name}`. Multiple actors can be overridden simultaneously:

```json
{
  "x-asya-route-override": {
    "model": "model-v2",
    "postprocess": "postprocess-experimental"
  }
}
```

#### Fanout ID and Lineage Tracking

The current fanout convention generates child IDs using `{parent_id}-{index}` suffixes. This causes ID collisions in nested fanout (actor A fans out `msg-1` into `msg-1-1`, then actor B fans out `msg-1` again and also produces `msg-1-1`). This RFC replaces the suffix convention with UUID-based child IDs and adds a `root_id` field for OTel trace correlation.

##### Current Behavior (replaced)

```
msg-1 -> Actor A (yields 3):
  Index 0: id = "msg-1"      parent_id = nil       (keeps original)
  Index 1: id = "msg-1-1"    parent_id = "msg-1"   (suffix convention)
  Index 2: id = "msg-1-2"    parent_id = "msg-1"   (suffix convention)
```

Nested fanout of `msg-1` at Actor B would produce `msg-1-1` again -- an ID collision.

##### New Behavior

Fanout children (index > 0) receive UUID-based IDs. The index-0 child still retains the original ID for SSE streaming compatibility:

```
msg-1 -> Actor A (yields 3):
  Index 0: id = "msg-1"              parent_id = nil
  Index 1: id = "f47ac10b-58cc"      parent_id = "msg-1"
  Index 2: id = "a8b3c2d1-99ee"      parent_id = "msg-1"
```

Nested fanout is now collision-free:

```
msg-1 -> Actor B (yields 2):
  Index 0: id = "msg-1"              parent_id = nil        (keeps original)
  Index 1: id = "c3d4e5f6-1122"      parent_id = "msg-1"   (unique UUID)
```

##### Lineage Fields

The message gains an optional `root_id` field:

```go
type Message struct {
    ID       string  `json:"id"`
    ParentID *string `json:"parent_id,omitempty"`
    RootID   *string `json:"root_id,omitempty"`
    Route    Route   `json:"route"`
    Headers  map[string]interface{} `json:"headers,omitempty"`
    Payload  json.RawMessage        `json:"payload"`
    Status   *Status                `json:"status,omitempty"`
}
```

`root_id` is optional and only set on fanout children. The derivation rule:

| Fanout depth | Fields present | OTel `trace_id` derivation |
|-------------|---------------|---------------------------|
| Root (no fanout) | `id` | `id` |
| Level 1 child | `id`, `parent_id` | `parent_id` |
| Level 2+ child | `id`, `parent_id`, `root_id` | `root_id` |

The sidecar derives `trace_id` as: `root_id ?? parent_id ?? id`.

When creating fanout children, the sidecar propagates `root_id` from the parent message. If the parent has no `root_id`, the sidecar uses the parent's `id` as the child's `root_id` (but only for level 2+; level-1 children omit `root_id` since `parent_id` is sufficient).

##### OTel Mapping

These fields map directly to OTel's distributed tracing model:

| Asya field | OTel equivalent | Notes |
|-----------|----------------|-------|
| `root_id ?? parent_id ?? id` | `trace_id` | Groups all messages from the same original |
| `id` | `span_id` | Unique per message |
| `parent_id` | `parent_span_id` | Immediate parent for tree reconstruction |

The tracing backend (Jaeger, Tempo) collects all spans with the same `trace_id` and reconstructs the full fanout tree from `parent_span_id` pointers. No ancestry list is needed in the message -- the backend builds the tree from the flat parent pointers, which is the standard OTel approach.

##### Example: Two-Level Nested Fanout

```
Original: {id: "abc"}

Actor A fans out (3 results):
  {id: "abc",              parent_id: nil,    root_id: nil}
  {id: "uuid-1",           parent_id: "abc",  root_id: nil}
  {id: "uuid-2",           parent_id: "abc",  root_id: nil}

Actor B fans out "uuid-1" (2 results):
  {id: "uuid-1",           parent_id: "abc",  root_id: nil}
  {id: "uuid-3",           parent_id: "uuid-1", root_id: "abc"}

OTel trace_id for all messages: "abc"
Tree reconstruction by backend:
  abc
  ├── uuid-1
  │   └── uuid-3
  └── uuid-2
```

Other functionality (gateway task tracking, fan-in correlation) uses its own custom headers and is not affected by these lineage fields.

#### Layer 1: Sidecar Changes

The change is confined to one function: `resolveQueueName()` in `src/asya-sidecar/internal/router/router.go`.

**Current logic** (lines 1133-1142):

```go
func (r *Router) resolveQueueName(actorName string) string {
    switch r.cfg.TransportType {
    case "rabbitmq", "sqs":
        return fmt.Sprintf("asya-%s-%s", r.cfg.Namespace, actorName)
    default:
        return actorName
    }
}
```

**Proposed logic**:

The `routeResponse()` function (line 649) passes the message headers to `resolveQueueName()`. The function checks for an override before resolving the queue:

```go
func (r *Router) resolveQueueName(actorName string, headers map[string]interface{}) string {
    resolvedName := actorName

    if overrides, ok := headers["x-asya-route-override"]; ok {
        if overrideMap, ok := overrides.(map[string]interface{}); ok {
            if target, ok := overrideMap[actorName]; ok {
                if targetStr, ok := target.(string); ok && targetStr != "" {
                    r.logger.Info("route override applied",
                        "original", actorName,
                        "target", targetStr,
                    )
                    resolvedName = targetStr
                }
            }
        }
    }

    switch r.cfg.TransportType {
    case "rabbitmq", "sqs":
        return fmt.Sprintf("asya-%s-%s", r.cfg.Namespace, resolvedName)
    default:
        return resolvedName
    }
}
```

**Behavioral properties**:

- **Deterministic**: Same headers always produce the same routing. No randomness in the sidecar.
- **Pass-through**: Override headers propagate through the entire pipeline. If `model` is overridden, every sidecar that routes to `model` will respect the override.
- **Additive**: Overrides do not modify the route. `route.actors` still says `["prep", "model", "post"]`. Only the queue destination changes.
- **No actor identity validation change needed**: The overridden actor (e.g., `model-v2`) is deployed as its own AsyncActor with its own queue (`asya-{ns}-model-v2`). It does not need to pretend to be `model`.

**Important**: The sidecar does NOT update `route.actors` or `route.current`. The route still shows the logical pipeline. The override only affects queue resolution. To surface which variant handled the message, the sidecar stamps `headers.x-asya-route-resolved` (see "Observability" section).

#### Actor Identity and Route Validation

When a message arrives at `model-v2` via an override, the route still says `route.actors[current] == "model"`. The sidecar at `model-v2` validates that the current actor matches its own name (`ASYA_ACTOR_NAME`).

Two options exist to handle this mismatch:

**Option A: Alias configuration.** The `model-v2` sidecar is configured with an alias list:

```yaml
env:
  - name: ASYA_ACTOR_NAME
    value: model-v2
  - name: ASYA_ACTOR_ALIASES
    value: model
```

The sidecar accepts messages where `route.actors[current]` matches either its name or any alias.

**Option B: Skip validation for overridden messages.** If the message has `x-asya-route-override` mapping `route.actors[current]` to `ASYA_ACTOR_NAME`, skip the actor name check. The override itself serves as authorization.

**Decision**: Option B. It requires no additional configuration on the variant actor. The presence of the override header is sufficient -- the sender explicitly chose to route here. Option A adds a configuration burden that grows with the number of experiments.

#### Layer 2: Router Actors

For probabilistic, conditional, or adaptive routing, a Python router actor makes the decision and stamps the override header. The router runs in envelope mode.

##### Pre-built Router: `asya-crew` Experiment Actor

A generic experiment router actor, deployed as part of `asya-crew`, configured entirely via environment variables:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: model-experiment
spec:
  image: asya-crew:latest
  handler: asya_crew.experiment.weighted_router
  handlerMode: envelope
  env:
    - name: ASYA_EXPERIMENT_NAME
      value: pricing-model-v2
    - name: ASYA_EXPERIMENT_TARGET
      value: model
    - name: ASYA_EXPERIMENT_VARIANTS
      value: "model:80,model-v2:20"
```

**Implementation** (Python):

```python
import os
import random

_EXPERIMENT_NAME = os.environ["ASYA_EXPERIMENT_NAME"]
_TARGET = os.environ["ASYA_EXPERIMENT_TARGET"]

# Parse "model:80,model-v2:20" into weighted choices
_raw = os.environ["ASYA_EXPERIMENT_VARIANTS"]
_variants = []
_weights = []
for part in _raw.split(","):
    name, weight = part.strip().rsplit(":", 1)
    _variants.append(name.strip())
    _weights.append(int(weight.strip()))


def weighted_router(envelope: dict) -> dict:
    chosen = random.choices(_variants, weights=_weights, k=1)[0]

    headers = envelope.get("headers", {})
    overrides = headers.get("x-asya-route-override", {})
    overrides[_TARGET] = chosen
    headers["x-asya-route-override"] = overrides
    headers["x-asya-experiment"] = _EXPERIMENT_NAME
    headers["x-asya-variant"] = chosen
    envelope["headers"] = headers

    return envelope
```

**Pipeline with experiment**:

```
route.actors: ["prep", "model-experiment", "model", "post"]
```

The `model-experiment` actor runs before `model`, stamps the override header. The sidecar at the `model-experiment` step routes the message to the next actor in the route (`model`). The next sidecar -- the one receiving the message destined for `model` -- reads the override header and sends to `model-v2`'s queue instead.

##### Custom Router Examples

Data Scientists can write fully custom routers for advanced use cases:

```python
# Multi-armed bandit router
import httpx

async def mab_router(envelope: dict) -> dict:
    stats = await httpx.get("http://metrics-service/experiment/pricing-v2")
    variant = select_variant_by_ucb1(stats.json())

    headers = envelope.setdefault("headers", {})
    overrides = headers.setdefault("x-asya-route-override", {})
    overrides["model"] = variant
    headers["x-asya-experiment"] = "pricing-v2"
    headers["x-asya-variant"] = variant

    return envelope
```

```python
# Fan-in sharding router
import hashlib
import os

SHARD_COUNT = int(os.environ["ASYA_SHARD_COUNT"])

def shard_router(envelope: dict) -> dict:
    user_id = envelope["payload"]["user_id"]
    shard = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % SHARD_COUNT

    headers = envelope.setdefault("headers", {})
    overrides = headers.setdefault("x-asya-route-override", {})
    overrides["aggregator"] = f"aggregator-shard-{shard}"

    return envelope
```

```python
# Sticky session router (consistent variant per user)
import hashlib
import os

_TARGET = os.environ["ASYA_EXPERIMENT_TARGET"]
_EXPERIMENT_NAME = os.environ["ASYA_EXPERIMENT_NAME"]
_raw = os.environ["ASYA_EXPERIMENT_VARIANTS"]
_variants = [part.strip().rsplit(":", 1)[0].strip() for part in _raw.split(",")]

def sticky_router(envelope: dict) -> dict:
    user_id = envelope["payload"].get("user_id", envelope["id"])
    variant_index = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % len(_variants)
    chosen = _variants[variant_index]

    headers = envelope.setdefault("headers", {})
    overrides = headers.setdefault("x-asya-route-override", {})
    overrides[_TARGET] = chosen
    headers["x-asya-experiment"] = _EXPERIMENT_NAME
    headers["x-asya-variant"] = chosen

    return envelope
```

##### Flow DSL Extension (Future)

The Flow DSL could support an `experiment()` primitive that generates the router actor automatically:

```python
def my_pipeline(p: dict) -> dict:
    p = preprocess(p)
    p = experiment("pricing-v2", target=model, variants={
        model_v1: 80,
        model_v2: 20,
    })
    p = postprocess(p)
    return p
```

The compiler would generate a router actor equivalent to the `asya-crew` experiment actor. This is out of scope for this RFC but should be designed to be compatible with the override header mechanism.

### Observability

#### Resolved Route Header

When the sidecar applies an override, it stamps a resolution trace:

```json
{
  "headers": {
    "x-asya-route-override": {"model": "model-v2"},
    "x-asya-route-resolved": {
      "model": {"target": "model-v2", "by": "prep"}
    }
  }
}
```

`x-asya-route-resolved` records which sidecar applied each override (`by` = the actor name of the sidecar that performed the queue rewrite). This enables:

- **Debugging**: "Which sidecar actually rerouted the message?"
- **Audit trail**: Full history of override applications in the message itself

#### Experiment Tracking Headers

Router actors stamp these headers for downstream observability:

| Header | Purpose | Example |
|--------|---------|---------|
| `x-asya-experiment` | Experiment name | `pricing-v2` |
| `x-asya-variant` | Selected variant | `model-v2` |
| `x-asya-route-override` | Override map (consumed by sidecar) | `{"model": "model-v2"}` |
| `x-asya-route-resolved` | Resolution audit trail (stamped by sidecar) | `{"model": {"target": "model-v2", "by": "prep"}}` |

These headers are preserved through the pipeline and available to:

- `happy-end` / `error-end` actors for per-variant metrics aggregation
- Gateway progress reporting for experiment dashboards
- User handlers (read-only) for variant-aware logging

#### Metrics

The sidecar emits a counter when an override is applied:

```
asya_route_override_applied_total{actor="model", target="model-v2", namespace="prod"}
```

The `happy-end` actor can aggregate per-variant success/error rates using the `x-asya-experiment` and `x-asya-variant` headers from the message.

### Use Cases

#### Use Case 1: Local Actor Testing (Layer 1 Only)

A Data Scientist wants to test a local version of `model` against staging traffic.

**Setup**: Deploy local actor as `model-local` AsyncActor. Send messages with override header:

```json
{
  "route": {"actors": ["prep", "model", "post"], "current": 0},
  "headers": {
    "x-asya-route-override": {"model": "model-local"}
  },
  "payload": {}
}
```

**Result**: 100% of messages with this header go to `model-local`. No pipeline changes. No router actors. One header.

#### Use Case 2: A/B Testing with Weighted Split (Layer 1 + Layer 2)

**Setup**: Deploy `model-v2` as a separate AsyncActor. Deploy the `asya-crew` experiment actor:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: model-experiment
spec:
  handler: asya_crew.experiment.weighted_router
  handlerMode: envelope
  env:
    - name: ASYA_EXPERIMENT_NAME
      value: model-ab-test
    - name: ASYA_EXPERIMENT_TARGET
      value: model
    - name: ASYA_EXPERIMENT_VARIANTS
      value: "model:90,model-v2:10"
```

Update the pipeline route to include the experiment router before the target actor:

```json
{
  "route": {"actors": ["prep", "model-experiment", "model", "post"], "current": 0}
}
```

**Result**: 90% of traffic goes to `model`, 10% to `model-v2`. Both variants report to `happy-end` with experiment headers for metrics comparison.

#### Use Case 3: Canary Deployment (Layer 1 + Layer 2)

Same as A/B testing but with progressive weight changes:

1. Start: `"model:99,model-canary:1"`
2. Monitor error rates via `happy-end` / `error-end` per-variant metrics
3. Increase: `"model:90,model-canary:10"`
4. Promote: `"model:0,model-canary:100"`

Weight changes require updating the environment variable on the experiment router actor (ConfigMap update + pod restart, or a future live-config mechanism).

#### Use Case 4: Fan-In Sharding (Layer 1 + Layer 2)

A stateful aggregator needs consistent routing based on a payload key.

**Setup**: Deploy `aggregator-shard-0` through `aggregator-shard-3` as separate AsyncActors. Deploy a custom shard router:

```python
def shard_router(envelope: dict) -> dict:
    user_id = envelope["payload"]["user_id"]
    shard = hash(user_id) % 4
    headers = envelope.setdefault("headers", {})
    headers.setdefault("x-asya-route-override", {})["aggregator"] = f"aggregator-shard-{shard}"
    return envelope
```

Pipeline: `["source", "shard-router", "aggregator", "sink"]`

**Result**: Messages with the same `user_id` always go to the same shard. Route says `aggregator` (business intent), override says `aggregator-shard-2` (operational detail).

#### Use Case 5: Multi-Armed Bandit (Layer 2)

A Data Scientist wants to dynamically shift traffic based on performance.

**Setup**: Deploy a custom MAB router that queries a metrics service, computes UCB1 or Thompson Sampling scores, and selects the best-performing variant. The router updates override headers on every message.

This use case requires a custom router actor (not the pre-built weighted router) because the routing logic depends on external state (metrics). The full flexibility of Python makes implementing custom bandit algorithms straightforward.

### Non-Goals

- **Automatic rollback**: This RFC does not define automatic rollback based on error rates. That requires a controller watching metrics and updating experiment config -- a separate concern.
- **Experiment lifecycle management**: Creating, starting, stopping, and archiving experiments is out of scope. This RFC defines the routing mechanism only.
- **Flow DSL integration**: The `experiment()` primitive for the Flow DSL is a future extension that should be designed after the core mechanism is validated.
- **Live config reloading**: Updating experiment weights without pod restarts requires a config-watching mechanism (ConfigMap watcher, external config service). Out of scope.

---

### Architecture Decision Records

#### ADR-1: Route Override via Headers, Not Route Modification

**Context**: A/B testing requires routing messages to variant actors. Two approaches exist: modify `route.actors` to include variant names, or use a separate mechanism (headers) to override routing without changing the route.

**Decision**: Use `headers["x-asya-route-override"]` to override routing. The `route.actors` array remains unchanged and continues to represent the logical pipeline.

**Rationale**:

- `route` is business logic (what the pipeline does). A/B testing is a non-functional concern (how traffic is managed). Mixing them violates separation of concerns.
- Routes are validated by the runtime (processed steps cannot be modified). Injecting variant names into the route array complicates validation.
- Overrides are transparent and debuggable: `headers` shows exactly what was overridden, `route` shows the intended pipeline.
- Multiple independent experiments can coexist in the same pipeline without route conflicts.

**Consequences**:

- Progress reporting shows logical actor names, not variant names. The `x-asya-route-resolved` header provides variant visibility.
- Actor identity validation needs to handle the mismatch between route (`model`) and actual destination (`model-v2`).

#### ADR-2: Static Sidecar Override, Programmatic Logic in Python

**Context**: The override mechanism could be "smart" (supporting probability, CEL conditions, MAB algorithms) or "dumb" (static name remapping only). Complex logic could live in the sidecar (Go) or in router actors (Python).

**Decision**: The sidecar performs a static dictionary lookup only. All probabilistic, conditional, and adaptive routing logic lives in Python router actors.

**Rationale**:

- **Slippery slope avoidance**: Adding probability to the sidecar leads to sticky sessions, then CEL conditions, then MAB, then metrics integration. The sidecar becomes a routing engine that Data Scientists cannot read or extend.
- **Python is the users' language**: Data Scientists read, write, and debug Python. Routing logic embedded in a Go sidecar or expressed in CEL is opaque to them.
- **Testability**: Python routers can be unit-tested with standard pytest. Sidecar routing logic requires Go integration tests.
- **Extensibility**: Custom MAB algorithms, external service calls, and domain-specific sharding logic are trivial in Python, non-trivial in a Go sidecar config format.
- **Two-language problem**: Adding CEL or a probability DSL means Data Scientists need to learn Python AND a second routing language. One language is better UX.
- **YAGNI**: The static override covers the high-frequency use case (local testing, 100% redirect). Complex experiments are rarer and justify the extra hop.

**Consequences**:

- Complex experiments incur one extra queue hop (router actor). For most pipelines this adds single-digit milliseconds of latency.
- Users must deploy a router actor for A/B testing (not just set a header). The `asya-crew` pre-built router minimizes this burden.

#### ADR-3: Skip Actor Identity Validation for Overridden Messages

**Context**: When a message is overridden from `model` to `model-v2`, the route still says `route.actors[current] == "model"` but the receiving sidecar's `ASYA_ACTOR_NAME` is `model-v2`. The sidecar normally validates that these match.

**Decision**: If the message has `x-asya-route-override` mapping `route.actors[current]` to `ASYA_ACTOR_NAME`, skip the actor name validation.

**Alternatives considered**:

- **Alias configuration** (`ASYA_ACTOR_ALIASES=model`): Explicit but adds configuration burden per experiment. Every variant actor needs to know which logical actors it might substitute for. Configuration grows linearly with experiments.
- **No validation at all**: Too permissive. Misrouted messages would be silently processed instead of detected.

**Rationale**: The override header is the authorization. If a message says "route `model` to `model-v2`" and it arrives at `model-v2`, the intent is clear. No additional configuration needed on the variant actor.

**Consequences**:

- Variant actors require zero special configuration to participate in experiments.
- A malformed override could bypass validation. This is acceptable because headers are set by trusted components (gateway, router actors), not by external users.

#### ADR-4: Override Headers Propagate Through the Pipeline

**Context**: Should override headers be consumed (removed) after the first application, or propagate through the entire pipeline?

**Decision**: Override headers propagate. They are never removed by the sidecar.

**Rationale**:

- A pipeline might route through the same logical actor multiple times (loops in Flow DSL). The override should apply consistently.
- Downstream actors and `happy-end`/`error-end` can read override headers for observability and per-variant metrics.
- Removing headers would require the sidecar to modify the message envelope, adding complexity and breaking the principle that the sidecar does not alter message content.

**Consequences**:

- If the pipeline contains the same actor name at multiple positions, the override applies to all of them. This is usually desired (same experiment applies consistently) but could surprise users who want per-position overrides. Per-position overrides can be achieved with distinct logical actor names.

#### ADR-5: UUID-Based Fanout IDs with Optional root_id

**Context**: The current fanout ID convention (`{parent_id}-{index}`) produces collisions in nested fanout scenarios. Additionally, OTel tracing requires a `trace_id` to group all messages from the same original, and a `parent_span_id` for tree reconstruction.

**Decision**: Replace the `{id}-{index}` suffix convention with UUID-based IDs for fanout children. Add an optional `root_id` field that is only present on level-2+ fanout children.

**Alternatives considered**:

- **`parent_id` as a list (full ancestry chain)**: Every message carries its complete lineage. Provides O(1) path reconstruction from a single message, but grows with depth, is non-standard for OTel (which uses flat `parent_span_id`), and the full tree still cannot be reconstructed from one message alone (siblings are invisible).
- **Actor-scoped suffixes** (`msg-1:prep.1:infer.1`): Encodes lineage in the ID itself. Avoids collisions but produces long, fragile IDs that require parsing for structure.
- **Dedicated `root_id` on every message**: Simpler derivation (`trace_id = root_id`) but wastes space on the 99% of messages that are not fanout children.

**Rationale**:

- UUIDs eliminate ID collisions entirely without encoding structure into IDs.
- The `root_id ?? parent_id ?? id` derivation keeps the common case (no fanout) zero-overhead -- no extra fields in the JSON.
- Flat `parent_id` + `root_id` maps directly to OTel's `parent_span_id` + `trace_id` model. Every tracing backend (Jaeger, Tempo) reconstructs trees from this pattern.
- Level-1 fanout children (the common case) omit `root_id` since `parent_id` already equals the root. Only level-2+ children (rare) carry `root_id`.

**Consequences**:

- Fanout child IDs are no longer human-readable sequences. Debugging relies on `parent_id` pointers and tracing UIs rather than reading ID suffixes.
- Index-0 children still retain the original ID for SSE streaming compatibility (unchanged).

#### ADR-6: No CEL or Expression Language in the Sidecar

**Context**: Adding condition evaluation (CEL, Rego, JSONPath) to the sidecar would eliminate the extra hop for conditional routing. Should the sidecar support inline expressions?

**Decision**: No expression language in the sidecar. All conditional logic lives in Python router actors.

**Rationale**:

- **Two languages problem**: Data Scientists would need to learn Python AND CEL. One language is better UX.
- **Dependency burden**: CEL evaluation adds a Go dependency, increases binary size, and introduces a potential attack surface in the sidecar.
- **Testing complexity**: CEL expressions in config files are harder to test than Python functions with pytest.
- **Diminishing returns**: The latency saved by avoiding one queue hop is negligible compared to the cognitive overhead of a second routing language.

**Consequences**:

- Every conditional routing scenario requires a router actor. This is intentional: conditional routing IS logic, and logic belongs in code, not config.

---

### Migration and Compatibility

#### Backward Compatibility

This proposal is fully backward compatible:

- **No protocol breaking changes**: `x-asya-route-override` is a new optional header. Existing messages without it route normally.
- **No route format changes**: `route.actors` and `route.current` semantics are unchanged.
- **No sidecar config changes**: The sidecar's `resolveQueueName()` function gains a headers parameter but existing behavior is preserved when no override is present.
- **No runtime changes**: The Python runtime does not participate in override routing.

#### Rollout Plan

1. **Phase 1**: Sidecar changes (Layer 1). Deploy updated sidecars that support `x-asya-route-override`. No behavior change for existing pipelines.
2. **Phase 2**: Pre-built router actor in `asya-crew`. Implement and deploy the `weighted_router` handler.
3. **Phase 3**: Documentation and examples for Data Scientists.
4. **Phase 4** (future): Flow DSL `experiment()` primitive.

### Security Considerations

- **Header trust boundary**: Override headers are set by trusted components (gateway, router actors within the cluster). External API consumers cannot inject override headers unless the gateway explicitly passes them through. The gateway should strip `x-asya-*` headers from external requests by default.
- **Queue existence**: Overriding to a non-existent actor (queue) will cause a publish failure, caught by existing sidecar error handling. The message routes to `error-end`.
- **No privilege escalation**: Overrides only affect queue routing. They cannot bypass authentication, authorization, or payload validation.

### Testing Strategy

#### Unit Tests (Sidecar)

- `resolveQueueName()` with override headers: correct target, missing actor, empty target string
- `resolveQueueName()` without override headers: existing behavior preserved
- `resolveQueueName()` with nil headers, empty override map, malformed override values
- Override does not modify `route.actors` or `route.current`
- `x-asya-route-resolved` header stamped correctly on override application
- Actor identity validation skipped when override matches `ASYA_ACTOR_NAME`
- Fanout children (index > 0) receive UUID-based IDs, not `{id}-{index}` suffixes
- Fanout index-0 child retains original ID (SSE compatibility)
- `parent_id` set correctly on fanout children
- `root_id` propagated from parent on level-2+ fanout; omitted on level-1
- OTel `trace_id` derivation: `root_id ?? parent_id ?? id`

#### Unit Tests (Router Actor)

- Weighted router distributes according to configured weights (statistical test over N iterations)
- Router stamps correct headers (`x-asya-experiment`, `x-asya-variant`, `x-asya-route-override`)
- Router preserves existing headers and existing overrides for other actors
- Router handles edge cases: single variant (100%), equal weights, zero weight

#### Component Tests

- Sidecar routes to overridden queue when header is present
- Sidecar routes normally when header is absent
- Override propagates through multi-actor pipeline unchanged

#### Integration Tests

- End-to-end pipeline with experiment router: verify traffic split matches configured weights (within statistical tolerance, e.g., chi-squared test)
- Override with non-existent target actor: verify `error-end` routing
- Multiple overrides in single message: verify all applied correctly
- Override at different pipeline positions: verify correct sidecar applies the override

### Open Questions

1. **Gateway header stripping**: Should the gateway strip `x-asya-route-override` headers from external API requests by default? This prevents external callers from injecting routing overrides. If so, should there be an explicit opt-in to allow external overrides (e.g., for testing)?

2. **ConfigMap-based live weight updates**: Should the experiment router watch ConfigMaps for live weight changes without pod restarts? This adds complexity but enables gradual canary rollouts without redeployment.

3. **Sticky sessions in pre-built router**: Should the `asya-crew` experiment router support sticky sessions (consistent variant per user based on a configurable payload key) as a built-in mode, or should that be a separate custom router?

4. **Override cleanup after experiment**: When an experiment ends (variant is promoted or rolled back), overrides in in-flight messages will continue to route to the old target. Should there be a mechanism to ignore stale overrides, or is this acceptable given queue drain timing?

### References

- [Asya Message Protocol](../../architecture/protocols/actor-actor.md)
- [Asya Sidecar Architecture](../../architecture/asya-sidecar.md)
- [Asya Flow DSL](../../architecture/asya-flow.md)
- [Flagger - Progressive Delivery](https://flagger.app/)
- [Argo Rollouts](https://argoproj.github.io/rollouts/)
- [Enterprise Integration Patterns - Content-Based Router](https://www.enterpriseintegrationpatterns.com/ContentBasedRouter.html)
