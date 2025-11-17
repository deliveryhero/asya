# Route CRD: Declarative Pipelines with Auto-Generated MCP Tools

**Status:** Draft
**Date:** 2025-11-11
**Authors:** System

## Problem

### Current Pipeline Implementation Complexity

Asya🎭's envelope protocol supports multi-actor pipelines through the `route.actors` array, but implementing pipelines requires significant manual configuration:

**Current workflow to create a pipeline:**
1. Deploy AsyncActor CRDs for each stage (e.g., `image-resizer`, `image-optimizer`, `thumbnail-generator`)
2. Manually create gateway tool configuration in `src/asya-gateway/config/tools.yaml`
3. Write tool logic to construct envelope with correct `route.actors` array
4. Restart gateway to load new tool configuration
5. Manually document the pipeline flow for team members
6. Repeat steps 2-4 for every pipeline change

**Problems this creates:**

1. **Configuration sprawl**: Pipeline definition is split across AsyncActor CRDs and gateway tool configs
2. **No validation**: Gateway tools can reference non-existent actors, causing runtime failures
3. **Poor discoverability**: No single place to see all available pipelines
4. **Manual synchronization**: Changing pipeline requires updating multiple files and restarting gateway
5. **No version control linkage**: Pipeline changes in AsyncActors don't automatically update gateway tools
6. **Operational overhead**: Teams must understand envelope protocol, route construction, and gateway tool API

### Motivating Scenarios

**Scenario 1: ML Inference Pipeline**
```
User wants: image → preprocessing → model-inference → postprocessing → results

Current implementation:
1. Create 3 AsyncActor CRDs (preprocessing-actor, inference-actor, postprocessing-actor)
2. Edit tools.yaml to add "run_inference" tool
3. Write route construction: {"actors": ["preprocessing-actor", "inference-actor", "postprocessing-actor"], "current": 0}
4. Document pipeline in README or Confluence
5. When adding new model, edit AsyncActor, edit tool, restart gateway

Desired: Single Route CRD that declares pipeline and auto-creates MCP tool
```

**Scenario 2: Multi-Stage Data Processing**
```
Team has 5 different data pipelines:
- ETL pipeline: extract → transform → load (3 actors)
- Analytics pipeline: collect → aggregate → analyze → visualize (4 actors)
- Validation pipeline: sanitize → validate → enrich (3 actors)
- Alert pipeline: detect → classify → notify (3 actors)
- Backup pipeline: snapshot → compress → upload (3 actors)

Current approach: 15 AsyncActors + 5 manual gateway tool configs
Problem: No clear view of which actors belong to which pipeline, tools.yaml becomes unmaintainable
```

**Scenario 3: Pipeline Evolution**
```
Pipeline v1: text-extractor → summarizer
Pipeline v2: text-extractor → translator → summarizer
Pipeline v3: text-extractor → classifier → summarizer (conditional routing in future)

Current approach: Edit tools.yaml, update route construction, restart gateway, update docs
Problem: Pipeline changes require coordinated edits across multiple files, no audit trail
```

## Motivation

### Key Insights

1. **Pipelines are first-class concepts**: Multi-actor workflows are common enough to deserve declarative support, not just protocol-level primitives.

2. **Gateway tools should be generated, not written**: Most MCP tools just submit envelopes with predefined routes - this is boilerplate that should be auto-generated.

3. **Namespace is the natural boundary**: Routes belong to a namespace alongside the actors they chain together.

4. **Configuration should be centralized**: A single Route CRD should declare actors, tool schema, and documentation - not scattered across files.

5. **Validation at deploy time beats runtime errors**: Route CRD can validate actors exist before creating gateway tools, preventing broken pipelines.

### Goals

1. **Simplify pipeline creation**: Declare pipeline in single YAML, get working MCP tool automatically
2. **Auto-generate gateway tools**: Route CRD creates corresponding MCP tool in gateway without manual config
3. **Centralize pipeline definition**: Route spec includes actors, input schema, description - no separate tool config
4. **Enable discoverability**: `kubectl get routes` shows all available pipelines
5. **Support versioning**: Route changes are version-controlled CRD updates, not manual edits
6. **Validate at creation time**: Route controller validates actors exist before creating gateway tools

### Non-Goals

1. **Replace envelope protocol**: Routes compile to envelope `route.actors` arrays, don't change sidecar behavior
2. **Conditional routing**: Initial version supports linear pipelines only (conditional/branching is future work)
3. **Deployment orchestration**: Routes don't deploy actors, just chain existing ones
4. **Health monitoring**: Route status shows existence, not runtime health (separate concern)

## Proposed Solution

### Route CRD

Introduce a namespace-scoped CRD that declares actor pipelines and auto-generates gateway MCP tools.

**API Design:**

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyaTool
metadata:
  name: image-processing-pipeline
  namespace: production
spec:
  # Ordered list of actors forming the pipeline
  # Compiled to envelope route.actors array
  actors:
    - image-resizer
    - image-optimizer
    - thumbnail-generator

  # MCP tool configuration
  # If enabled, gateway auto-creates tool with this spec
  tool:
    # Tool name exposed via MCP
    # Must be unique within namespace
    name: process_image

    # Human-readable description shown in MCP tool list
    description: "Resize, optimize, and generate thumbnails for uploaded images"

    # JSON Schema for tool input
    # Gateway validates input against this schema
    # Schema is passed to first actor in pipeline as envelope payload
    inputSchema:
      type: object
      required:
        - image_url
      properties:
        image_url:
          type: string
          format: uri
          description: "URL of the image to process"
        max_width:
          type: integer
          default: 1920
          description: "Maximum width in pixels"
        max_height:
          type: integer
          default: 1080
          description: "Maximum height in pixels"
        quality:
          type: integer
          minimum: 1
          maximum: 100
          default: 85
          description: "JPEG quality (1-100)"

  # Optional: Additional envelope headers
  # Merged into all envelopes submitted via this route
  headers:
    priority: high
    team: media-processing

  # Optional: Result tracking configuration
  # Controls how gateway tracks envelope through pipeline
  tracking:
    # Enable SSE streaming for this route's envelopes
    streamResults: true

    # Timeout for pipeline execution
    timeout: 5m

status:
  # Validation results
  conditions:
    - type: ActorsReady
      status: "True"
      reason: AllActorsExist
      message: "All 3 actors exist in namespace"
      lastTransitionTime: "2025-11-11T10:30:00Z"

    - type: ToolReady
      status: "True"
      reason: ToolRegistered
      message: "MCP tool 'process_image' registered in gateway"
      lastTransitionTime: "2025-11-11T10:30:15Z"

    - type: Ready
      status: "True"
      reason: RouteHealthy
      message: "Route is ready for use"
      lastTransitionTime: "2025-11-11T10:30:15Z"

  # Per-actor validation status
  actors:
    - name: image-resizer
      exists: true
      ready: true
      lastChecked: "2025-11-11T10:35:00Z"

    - name: image-optimizer
      exists: true
      ready: true
      lastChecked: "2025-11-11T10:35:00Z"

    - name: thumbnail-generator
      exists: true
      ready: true
      lastChecked: "2025-11-11T10:35:00Z"

  # Gateway tool registration status
  tool:
    name: process_image
    registered: true
    gatewayPod: asya-gateway-7d4c5f8b9-x2j4k
    lastUpdated: "2025-11-11T10:30:15Z"

  # Summary metrics
  summary:
    totalActors: 3
    readyActors: 3
    toolRegistered: true
    lastUpdated: "2025-11-11T10:35:00Z"
```

### Controller Architecture

**New controller: RouteReconciler**

Runs cluster-wide, performs namespace-scoped reconciliation.

**Responsibilities:**
1. Watch Route resources in all namespaces
2. Validate that all actors in `spec.actors` exist in the namespace
3. Notify gateway to register/update MCP tool based on `spec.tool`
4. Update Route status with validation results and tool registration status
5. Handle Route deletion by unregistering tools from gateway

**Does NOT:**
- Create or manage AsyncActor resources
- Deploy infrastructure
- Track runtime envelope processing
- Implement health monitoring

**Reconciliation Logic:**

```go
func (r *RouteReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    var route asyav1alpha1.Route
    if err := r.Get(ctx, req.NamespacedName, &route); err != nil {
        if apierrors.IsNotFound(err) {
            // Route deleted - unregister tool from gateway
            return ctrl.Result{}, r.unregisterTool(ctx, req.NamespacedName)
        }
        return ctrl.Result{}, err
    }

    // Validate actors exist
    actorStatus := r.validateActors(ctx, route.Namespace, route.Spec.Actors)

    // Check if all actors ready
    allActorsReady := true
    for _, status := range actorStatus {
        if !status.Exists || !status.Ready {
            allActorsReady = false
            break
        }
    }

    // Register/update tool in gateway if actors ready
    var toolStatus ToolStatus
    if allActorsReady && route.Spec.Tool.Name != "" {
        toolStatus = r.registerOrUpdateTool(ctx, &route)
    }

    // Update status
    r.updateRouteStatus(ctx, &route, actorStatus, toolStatus)

    // Requeue for periodic validation
    return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
}

func (r *RouteReconciler) validateActors(ctx context.Context, namespace string, actorNames []string) []ActorStatus {
    var statuses []ActorStatus

    for _, name := range actorNames {
        actor := &asyav1alpha1.AsyncActor{}
        err := r.Get(ctx, client.ObjectKey{
            Name: name, Namespace: namespace,
        }, actor)

        if err != nil {
            statuses = append(statuses, ActorStatus{
                Name:   name,
                Exists: false,
                Ready:  false,
                Error:  err.Error(),
            })
            continue
        }

        ready := meta.IsStatusConditionTrue(actor.Status.Conditions, "Ready")
        statuses = append(statuses, ActorStatus{
            Name:   name,
            Exists: true,
            Ready:  ready,
        })
    }

    return statuses
}

func (r *RouteReconciler) registerOrUpdateTool(ctx context.Context, route *asyav1alpha1.Route) ToolStatus {
    // Construct tool registration request
    toolSpec := GatewayToolSpec{
        Name:        route.Spec.Tool.Name,
        Description: route.Spec.Tool.Description,
        InputSchema: route.Spec.Tool.InputSchema,
        Route: RouteInfo{
            Actors:  route.Spec.Actors,
            Headers: route.Spec.Headers,
        },
        Namespace: route.Namespace,
    }

    // Send to gateway via HTTP API or shared ConfigMap
    // (Implementation detail: gateway watches ConfigMap or provides registration endpoint)
    err := r.gatewayClient.RegisterTool(ctx, toolSpec)

    return ToolStatus{
        Name:       route.Spec.Tool.Name,
        Registered: err == nil,
        Error:      err,
    }
}
```

### Gateway Integration

**Gateway changes required:**

1. **Tool registration endpoint/ConfigMap watching**
   - Gateway watches ConfigMap containing Route-generated tool specs
   - Or: Gateway provides HTTP endpoint for tool registration (operator calls it)

2. **Dynamic tool loading**
   - Gateway loads tool specs from ConfigMap at startup and on changes
   - No need to restart gateway when Routes are created/updated

3. **Tool execution**
   - When tool is called, gateway constructs envelope:
     ```json
     {
       "id": "<generated-id>",
       "route": {
         "actors": ["actor1", "actor2", "actor3"],  // From Route spec
         "current": 0
       },
       "headers": {...},  // From Route spec.headers + tool invocation metadata
       "payload": {...}   // From tool input, validated against inputSchema
     }
     ```
   - Submits envelope to first actor's queue (`asya-actor1`)
   - Tracks envelope through pipeline if `tracking.streamResults: true`

**ConfigMap approach (simpler, no new gateway API):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: asya-route-tools
  namespace: production
data:
  tools.json: |
    [
      {
        "name": "process_image",
        "description": "Resize, optimize, and generate thumbnails",
        "inputSchema": {...},
        "route": {
          "actors": ["image-resizer", "image-optimizer", "thumbnail-generator"],
          "headers": {"priority": "high"}
        }
      }
    ]
```

Route controller updates this ConfigMap, gateway watches for changes and reloads tools.

### Usage Workflow

**Step 1: Deploy actors**
```bash
kubectl apply -f - <<EOF
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: image-resizer
  namespace: production
spec:
  image: myregistry/image-resizer:v1.0
  transport: rabbitmq
---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: image-optimizer
  namespace: production
spec:
  image: myregistry/image-optimizer:v1.0
  transport: rabbitmq
---
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: thumbnail-generator
  namespace: production
spec:
  image: myregistry/thumbnail-generator:v1.0
  transport: rabbitmq
EOF
```

**Step 2: Create Route (declares pipeline, auto-creates tool)**
```bash
kubectl apply -f - <<EOF
apiVersion: asya.sh/v1alpha1
kind: Route
metadata:
  name: image-processing-pipeline
  namespace: production
spec:
  actors:
    - image-resizer
    - image-optimizer
    - thumbnail-generator
  tool:
    name: process_image
    description: "Resize, optimize, and generate thumbnails for uploaded images"
    inputSchema:
      type: object
      required: [image_url]
      properties:
        image_url:
          type: string
          description: "URL of the image to process"
  tracking:
    streamResults: true
EOF
```

**Step 3: Verify Route status**
```bash
kubectl get route image-processing-pipeline -n production
# NAME                         ACTORS   READY   TOOL              AGE
# image-processing-pipeline    3/3      True    process_image     30s

kubectl describe route image-processing-pipeline -n production
# Status:
#   Conditions:
#     Type          Status  Reason           Message
#     ----          ------  ------           -------
#     ActorsReady   True    AllActorsExist   All 3 actors exist
#     ToolReady     True    ToolRegistered   Tool 'process_image' registered
#     Ready         True    RouteHealthy     Route is ready
```

**Step 4: Use auto-generated MCP tool**
```bash
# Tool appears automatically in MCP tools list
# No manual gateway configuration needed
```

### Benefits

**For developers:**
- ✅ Single YAML declares entire pipeline - no scattered configuration
- ✅ Tool auto-generated - no manual tools.yaml editing
- ✅ Input schema validated - prevents invalid tool calls
- ✅ Version control friendly - pipeline changes are Git diffs
- ✅ Self-documenting - Route spec shows actors, schema, description

**For operators/SREs:**
- ✅ `kubectl get routes` shows all pipelines at a glance
- ✅ Route status shows validation errors before runtime
- ✅ No gateway restarts needed - tools load dynamically
- ✅ Namespace isolation - teams manage their own routes
- ✅ Clear ownership - Route lives with actors it chains

**For platform teams:**
- ✅ Reduces gateway configuration complexity
- ✅ Standardizes pipeline declaration across teams
- ✅ Enables discoverability - routes are Kubernetes resources
- ✅ Supports GitOps workflows - routes are declarative CRDs
- ✅ Optional adoption - existing tools.yaml configs still work

### Implementation Phases

**Phase 1: CRD Definition** (2-3 hours)
- Define Route CRD schema
- Add validation rules (unique tool names, actor list non-empty, etc.)
- Generate CRD manifests with `make manifests`
- Write CRD documentation

**Phase 2: Basic Controller** (4-5 hours)
- Implement RouteReconciler
- Actor existence validation logic
- Status update logic
- Event emission for status changes

**Phase 3: Gateway Integration - ConfigMap Approach** (3-4 hours)
- Route controller updates ConfigMap with tool specs
- Gateway watches ConfigMap and loads tools dynamically
- Tool execution: construct envelope from Route spec
- Testing: verify tools work end-to-end

**Phase 4: Tool Schema Validation** (2-3 hours)
- Gateway validates tool input against `inputSchema`
- Return clear errors for invalid inputs
- Unit tests for schema validation

**Phase 5: Tracking Integration** (2-3 hours)
- Implement `tracking.streamResults` flag
- Gateway tracks route-based envelopes via SSE
- Add timeout support from `tracking.timeout`

**Phase 6: Documentation & Examples** (2-3 hours)
- Example Route manifests
- Migration guide from tools.yaml to Routes
- Best practices documentation
- Update architecture docs

**Total effort: ~15-21 hours**

## Examples

### Example 1: Simple Data Pipeline

```yaml
apiVersion: asya.sh/v1alpha1
kind: Route
metadata:
  name: etl-pipeline
  namespace: analytics
spec:
  actors:
    - data-extractor
    - data-transformer
    - data-loader
  tool:
    name: run_etl
    description: "Extract, transform, and load data from source to warehouse"
    inputSchema:
      type: object
      required: [source_url, destination_table]
      properties:
        source_url:
          type: string
          description: "URL of data source"
        destination_table:
          type: string
          description: "Target table name"
        batch_size:
          type: integer
          default: 1000
  tracking:
    streamResults: true
    timeout: 10m
```

### Example 2: ML Inference Pipeline

```yaml
apiVersion: asya.sh/v1alpha1
kind: Route
metadata:
  name: text-analysis-pipeline
  namespace: ml-models
spec:
  actors:
    - text-preprocessor
    - sentiment-classifier
    - entity-extractor
    - result-formatter
  tool:
    name: analyze_text
    description: "Analyze text sentiment and extract named entities"
    inputSchema:
      type: object
      required: [text]
      properties:
        text:
          type: string
          minLength: 1
          maxLength: 10000
          description: "Text to analyze"
        language:
          type: string
          enum: [en, es, fr, de]
          default: en
          description: "Text language"
  headers:
    model_version: "v2.5"
    team: ml-inference
  tracking:
    streamResults: true
    timeout: 30s
```

### Example 3: Multi-Stage Video Processing

```yaml
apiVersion: asya.sh/v1alpha1
kind: Route
metadata:
  name: video-processing-pipeline
  namespace: media
spec:
  actors:
    - video-downloader
    - video-transcoder
    - thumbnail-extractor
    - quality-analyzer
    - cdn-uploader
  tool:
    name: process_video
    description: "Download, transcode, analyze, and upload video to CDN"
    inputSchema:
      type: object
      required: [video_url, output_format]
      properties:
        video_url:
          type: string
          format: uri
          description: "Source video URL"
        output_format:
          type: string
          enum: [mp4, webm, hls]
          description: "Target video format"
        resolution:
          type: string
          enum: ["720p", "1080p", "4k"]
          default: "1080p"
        bitrate:
          type: integer
          description: "Target bitrate in kbps"
  tracking:
    streamResults: true
    timeout: 30m
```

## Alternatives Considered

### Alternative 1: Enhanced tools.yaml configuration

**Approach**: Extend gateway `tools.yaml` to support route declarations inline.

**Rejected because:**
- Tools.yaml is not version-controlled with actors
- No validation that actors exist
- No Kubernetes-native discoverability
- Requires gateway restart for changes
- Doesn't integrate with kubectl/GitOps workflows

### Alternative 2: Annotation-based pipeline declaration

**Approach**: Use AsyncActor annotations to declare "next actor" in pipeline.

```yaml
metadata:
  annotations:
    asya.sh/next-actor: image-optimizer
```

**Rejected because:**
- No central view of complete pipeline
- Hard to trace multi-actor flows
- Circular dependency detection is complex
- Tool generation requires scanning all actors
- Unclear ownership of pipeline definition

### Alternative 3: Gateway-managed routes via API

**Approach**: Gateway provides REST API to create routes, stores them internally.

**Rejected because:**
- Not Kubernetes-native (no kubectl integration)
- State management complexity in gateway
- Doesn't integrate with GitOps workflows
- No validation that actors exist
- Scaling/HA challenges for stateful gateway

### Alternative 4: Extend AsyncActor CRD with routes field

**Approach**: Add `spec.routes` to AsyncActor to declare pipelines it participates in.

**Rejected because:**
- Route is multi-actor concept, shouldn't live in single actor
- Duplicated configuration across multiple actors
- Unclear which actor "owns" the route
- Complicates AsyncActor API surface

## Migration Strategy

Routes are **fully optional** and coexist with existing tools.yaml configuration:

**Existing deployments (tools.yaml only):**
- Continue working exactly as before
- Gateway loads tools from `config/tools.yaml`
- No changes required

**New deployments (Routes):**
- Create Route CRDs for declarative pipelines
- Gateway loads tools from Routes ConfigMap
- Use kubectl to manage pipelines

**Hybrid approach (both tools.yaml and Routes):**
- Gateway loads tools from both sources
- Tool name conflicts: Route-generated tools take precedence (configurable)
- Gradual migration: create Routes for new pipelines, keep existing tools.yaml

**Migration path:**
1. Deploy Route controller alongside operator
2. Existing tools.yaml configs continue working
3. New pipelines use Route CRDs
4. Gradually migrate tools.yaml entries to Routes
5. Eventually deprecate tools.yaml (optional, not required)

## Future Enhancements

**Conditional routing** (beyond Phase 1):
```yaml
spec:
  actors:
    - classifier
  conditionalRoutes:
    - condition: "payload.category == 'urgent'"
      actors: [urgent-processor, notifier]
    - condition: "payload.category == 'standard'"
      actors: [standard-processor]
```

**Route composition** (nested routes):
```yaml
spec:
  actors:
    - preprocessor
    - route://image-processing-pipeline  # Reference another Route
    - postprocessor
```

**Rate limiting per route**:
```yaml
spec:
  rateLimit:
    requestsPerSecond: 100
    burstSize: 20
```

**Route-level autoscaling hints**:
```yaml
spec:
  autoscaling:
    suggestedMinReplicas: 2
    suggestedMaxReplicas: 10
```

## Open Questions

1. **Tool name conflicts**: What happens if two Routes in same namespace declare same tool name?
   - **Recommendation**: Validation webhook rejects duplicate tool names in same namespace

2. **Route updates**: How does gateway handle Route updates (actor list changes, schema changes)?
   - **Recommendation**: Controller updates ConfigMap, gateway reloads tools, in-flight envelopes complete with old route

3. **Tool execution priority**: Do Route-generated tools take precedence over tools.yaml tools?
   - **Recommendation**: Yes, with configurable flag `--prefer-route-tools=true` (default true)

4. **Cross-namespace routes**: Should Routes reference actors in different namespaces?
   - **Recommendation**: No, keep Routes namespace-scoped for Phase 1 (future enhancement if needed)

5. **Route deletion**: What happens to in-flight envelopes when Route is deleted?
   - **Recommendation**: Tool unregistered immediately, in-flight envelopes complete normally (actors still exist)

## References

- AsyncActor CRD: `src/asya-operator/api/v1alpha1/asyncactor_types.go`
- Envelope protocol: `CLAUDE.md` section "Envelope Protocol"
- Gateway tool configuration: `src/asya-gateway/config/README.md`
- MCP protocol: Gateway MCP implementation

## Next Steps

1. Review proposal with maintainers
2. Get feedback on Route API design and gateway integration approach
3. Decide between ConfigMap vs HTTP API for tool registration
4. Create GitHub issue for implementation tracking
5. Break down implementation into subtasks
6. Assign to milestone (likely v0.3.0)
