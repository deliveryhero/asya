---
title: Dynamic tool configuration loading for asya-gateway
status: open
priority: 2 # medium
type: task
tags:
  - type:feature
---



## Problem

Currently, asya-gateway loads tool configuration **once at startup** from YAML files via `ASYA_CONFIG_PATH`. Any changes to tools require a full gateway restart, which:

- Interrupts active SSE connections and in-flight requests
- Creates deployment friction for rapid iteration
- Prevents dynamic tool registration from other components

## Use Case

**asya-stagedoor workflow**:
1. User asks stagedoor to deploy a new flow/actor pipeline
2. Stagedoor talks to K8s API to create AsyncActor CRDs
3. Stagedoor registers the new flow as an MCP tool in asya-gateway
4. Tool becomes available immediately without gateway restart

## Proposed Solution

### Option A: Kubernetes CRD-based Configuration

Create a new CRD `AsyncTool` that asya-gateway watches:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncTool
metadata:
  name: text-analysis
  namespace: asya-e2e
spec:
  name: analyze_text
  description: Analyze text for sentiment and entities
  parameters:
    text:
      type: string
      required: true
  route: [tokenizer, sentiment, entity-extractor]
  progress: true
  timeout: 120
```

**Benefits**:
- Native K8s experience (kubectl, GitOps, RBAC)
- Operator can validate tool references actual AsyncActors
- Natural fit for stagedoor workflow
- Audit trail via K8s events

### Option B: ConfigMap Watch

Watch ConfigMap changes using K8s informers:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-tools
  labels:
    asya.dev/gateway-config: 'true'
data:
  analyze-text.yaml: |
    name: analyze_text
    ...
```

**Benefits**:
- Simpler implementation (no new CRD)
- Works with existing config format

**Drawbacks**:
- No schema validation at K8s level
- Harder to reference from stagedoor

### Option C: Hybrid (File Watch + Signal)

- Watch config directory for changes (fsnotify)
- Support SIGHUP for manual reload trigger
- Kubernetes can update ConfigMap volumes

**Benefits**:
- Works outside K8s too
- Simple implementation

**Drawbacks**:
- ConfigMap volume updates have propagation delay
- No K8s-native integration

## Technical Considerations

1. **Thread-safe registry updates**: Registry must support concurrent reads during updates
2. **Graceful tool removal**: What happens to in-flight requests for removed tools?
3. **Validation**: New tools should be validated before registration
4. **Tool name conflicts**: Handle duplicate names across sources
5. **Ordering**: CRD tools vs file-based tools precedence
6. **MCP protocol**: Does StreamableHTTP require re-initialization on tool change?

## Acceptance Criteria

- [ ] Gateway can detect new tool configurations without restart
- [ ] New tools become available within seconds of creation
- [ ] Removed tools are gracefully handled
- [ ] In-flight requests for removed tools complete normally
- [ ] Works with stagedoor for end-to-end flow registration
- [ ] Backwards compatible with static YAML configuration


---
_Migrated from beads `asya-vdc`_
