## RFC: Rename "Flavor" to "Overlay"

### 1. Motivation

The term **flavor** is currently used for composable configuration presets —
partial AsyncActor specs stored as Crossplane EnvironmentConfigs and merged via
strategic merge patch. We want to reclaim "flavor" for a new, user-facing concept:
**pre-built Docker images** that simplify the data scientist workflow (closer to
code-level, less infra-level).

The replacement term is **overlay**. The rationale:

| Criterion | Why "overlay" wins |
|-----------|--------------------|
| **Mechanism hint** | "Lay this config over that" — self-documenting API. Users immediately understand merge/layer semantics without reading docs. |
| **K8s ecosystem echo** | Kustomize established "overlay" for partial configs merged on top of a base. Platform engineers already carry this mental model. |
| **Ordering intuition** | "Overlays are stacked, later wins" — matches the left-to-right merge order exactly. |
| **No ecosystem collision** | Unlike "patch" (Crossplane's own `patches:` field), "overlay" has no naming conflict in the Crossplane pipeline. |
| **Config, not behavior** | Unlike "mixin" (adds methods in Python/Ruby) or "trait" (OAM behaviors), "overlay" clearly denotes layered configuration data. |

### 2. Merge Order Clarification

The rename also corrects a conceptual framing issue. The original RFC described the
merge as "flavor[0] is applied to a base, then flavor[1], ..., then actor inline
spec." But there is no separate "base" — **the first overlay IS the base**:

```
overlay[0]          <-- base layer
  + overlay[1]      <-- applied on top
  + ...
  + overlay[N]      <-- applied on top
  + actor inline    <-- final override (user always wins)
```

The actor's own inline spec (`spec.scaling`, `spec.workload`) is applied last and
always wins. This gives developers full control to override any overlay setting.

### 3. Scope

This is a **pure rename** — no behavioral changes. The strategic merge patch logic,
Crossplane composition pipeline architecture, and EnvironmentConfig storage model
remain identical. Only names, labels, comments, and documentation change.

### 4. Change Inventory

#### 4.1 Go Source: `src/function-asya-flavors/` -> `src/function-asya-overlays/`

**Directory rename**: `src/function-asya-flavors/` -> `src/function-asya-overlays/`

**`go.mod`**:
```
- module github.com/deliveryhero/asya/function-asya-flavors
+ module github.com/deliveryhero/asya/function-asya-overlays
```

**`fn.go`** — constants and identifiers:
```go
// Before
ContextKeyResolvedSpec = "asya.sh/resolved-spec"   // unchanged
FlavorLabel            = "asya.sh/flavor"

// After
ContextKeyResolvedSpec = "asya.sh/resolved-spec"   // unchanged
OverlayLabel           = "asya.sh/overlay"
```

All functions and variables rename `flavor` -> `overlay`:
| Before | After |
|--------|-------|
| `getFlavors(oxr)` | `getOverlays(oxr)` |
| `flavorResourceKey(flavor)` | `overlayResourceKey(overlay)` |
| `setRequirements(rsp, flavors)` | `setRequirements(rsp, overlays)` |
| `allFlavorsAvailable(required, flavors)` | `allOverlaysAvailable(required, overlays)` |
| `extractFlavorData(required, flavors, log)` | `extractOverlayData(required, overlays, log)` |
| `MergeFlavors(flavorData)` | `MergeOverlays(overlayData)` |
| `spec["flavors"]` | `spec["overlays"]` |
| `"flavor-" + flavor` (resource key prefix) | `"overlay-" + overlay` |
| `Function` struct comment | Update to reference "overlays" |

**`merge.go`** — function rename only:
```go
- func MergeFlavors(flavorData []map[string]interface{}) (...)
+ func MergeOverlays(overlayData []map[string]interface{}) (...)
```

Comments referencing "flavor" in `ActorSpecSchema`, `ApplyStrategicMerge` updated.

**`main.go`** — CLI description:
```go
- "A Crossplane Composition Function that resolves actor flavors."
+ "A Crossplane Composition Function that resolves actor overlays."
```

**`fn_test.go`** and **`merge_test.go`** — all test names, variables, comments.

**`Makefile`** — output messages referencing `function-asya-flavors`.

#### 4.2 XRD Schema

**`deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml`**:
```yaml
# Before
flavors:
  type: array
  maxItems: 8
  items:
    type: string
    minLength: 3
  description: >-
    List of flavor names (EnvironmentConfigs) to compose.
    Applied left-to-right; later flavors override earlier ones.
    Actor inline spec is applied last and always wins.

# After
overlays:
  type: array
  maxItems: 8
  items:
    type: string
    minLength: 3
  description: >-
    List of overlay names (EnvironmentConfigs) to compose.
    Applied left-to-right; later overlays override earlier ones.
    Actor inline spec is applied last and always wins.
```

#### 4.3 Crossplane Compositions

**`deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml`** and
**`deploy/helm-charts/asya-crossplane/templates/composition-rabbitmq.yaml`**:

```yaml
# Before
{{- if .Values.functions.flavorsEnabled }}
# Resolve actor flavors -- merges EnvironmentConfig flavor data into a resolved spec
- step: resolve-flavors
  functionRef:
    name: function-asya-flavors
{{- end }}

# After
{{- if .Values.functions.overlaysEnabled }}
# Resolve actor overlays -- merges EnvironmentConfig overlay data into a resolved spec
- step: resolve-overlays
  functionRef:
    name: function-asya-overlays
{{- end }}
```

#### 4.4 Crossplane Providers

**`deploy/helm-charts/asya-crossplane/templates/providers.yaml`**:
```yaml
# Before
name: function-asya-flavors
package: ghcr.io/deliveryhero/function-asya-flavors:{{ .Values.functions.flavorsVersion }}
packagePullPolicy: {{ .Values.functions.flavorsPackagePullPolicy }}

# After
name: function-asya-overlays
package: ghcr.io/deliveryhero/function-asya-overlays:{{ .Values.functions.overlaysVersion }}
packagePullPolicy: {{ .Values.functions.overlaysPackagePullPolicy }}
```

#### 4.5 Helm Values

**`deploy/helm-charts/asya-crossplane/values.yaml`**:
```yaml
# Before
flavorsVersion: "latest"
flavorsPackagePullPolicy: IfNotPresent

# After
overlaysVersion: "latest"
overlaysPackagePullPolicy: IfNotPresent
```

#### 4.6 EnvironmentConfig Labels

All EnvironmentConfigs change their label key:
```yaml
# Before
labels:
  asya.sh/flavor: gpu-t4
  asya.sh/flavor-dimension: compute
  asya.sh/flavor-owner: platform

# After
labels:
  asya.sh/overlay: gpu-t4
  asya.sh/overlay-dimension: compute
  asya.sh/overlay-owner: platform
```

#### 4.7 E2E Test Infrastructure

**`testing/e2e/profiles/sqs-s3.yaml`** and **`testing/e2e/profiles/rabbitmq-minio.yaml`**:
```yaml
# Before
flavorsEnabled: false
flavorsPackagePullPolicy: Never

# After
overlaysEnabled: false
overlaysPackagePullPolicy: Never
```

**`testing/e2e/charts/values.yaml`**:
```yaml
# Before
flavorsPackagePullPolicy: Never

# After
overlaysPackagePullPolicy: Never
```

**`testing/e2e/charts/asya-test-actors/templates/environment-configs.yaml`**:
```yaml
# Before
labels:
  asya.sh/flavor: asya-test-actor
# ...
labels:
  asya.sh/flavor: asya-test-env-vars

# After
labels:
  asya.sh/overlay: asya-test-actor
# ...
labels:
  asya.sh/overlay: asya-test-env-vars
```

**`testing/e2e/charts/asya-test-actors/templates/actor-*.yaml`** (10 files):
```yaml
# Before
flavors: ...

# After
overlays: ...
```

**`testing/e2e/tests/test_crossplane_e2e.py`**:
- Parameter `flavors: list[str] | None` -> `overlays: list[str] | None`
- YAML block generation: `flavors_block` -> `overlays_block`
- Test function: `test_asyncactor_flavors_resolved` -> `test_asyncactor_overlays_resolved`
- All string references and comments

#### 4.8 E2E Deploy Script

**`testing/e2e/scripts/deploy.sh`**:
- Comments referencing `function-asya-flavors`

#### 4.9 Build Scripts

**`Makefile`** (root) — all references to `src/function-asya-flavors`:
```makefile
# Before
cd src/function-asya-flavors && go mod download && go mod tidy
$(MAKE) -C src/function-asya-flavors test-unit
$(MAKE) -C src/function-asya-flavors cov-unit
$(MAKE) -C src/function-asya-flavors build
$(MAKE) -C src/function-asya-flavors clean

# After
cd src/function-asya-overlays && go mod download && go mod tidy
$(MAKE) -C src/function-asya-overlays test-unit
$(MAKE) -C src/function-asya-overlays cov-unit
$(MAKE) -C src/function-asya-overlays build
$(MAKE) -C src/function-asya-overlays clean
```

**`src/build-images.sh`**:
- Image name: `function-asya-flavors` -> `function-asya-overlays`

#### 4.10 GitHub Config

**`.github/release-drafter.yml`**:
- All references to `function-asya-flavors` -> `function-asya-overlays`

#### 4.11 Aint Issues (documentation-only updates)

These reference "flavor" in their text and should be updated for consistency:

- `.aint/epics/debt/task.peeped.1jnjkn.e2e-enable-function-asya-flavors-once-ghcr-io.md`
  - Title and body: `function-asya-flavors` -> `function-asya-overlays`
- `.aint/epics/docs/task.slopped.1f8jvk.document-example-flavor-environmentconfi-asya-quickstart.md`
  - Title and body: `flavor` -> `overlay`

Closed aint files (in `.closed/`) are historical records and should NOT be modified.

#### 4.12 AGENTS.md / CLAUDE.md

Update the Asya Flow DSL section example that shows `flavors: [gpu-t4, openai-keys]`
in the example AsyncActor YAML to use `overlays:`.

### 5. What Does NOT Change

| Item | Reason |
|------|--------|
| `ContextKeyResolvedSpec = "asya.sh/resolved-spec"` | Pipeline-internal context key, not user-facing. "Resolved spec" is still accurate. |
| Strategic merge patch logic (`ApplyStrategicMerge`) | Pure rename, no behavioral change. |
| `ActorSpecSchema` / `ScalingSchema` / `WorkloadSchema` | These describe the actor spec structure, not the overlay concept. |
| EnvironmentConfig `data` field structure | The data format is K8s-native and unchanged. |
| Merge order semantics | Left-to-right overlay merge, actor inline wins. |
| Closed aint issues (`.closed/`) | Historical records, not modified. |
| `CHANGELOG.md` | Historical record of past releases. |

### 6. Migration Path

This is a **pre-GA rename**. The `function-asya-flavors` image has never been
published to a public registry (the E2E task to enable it is still pending). No
external users exist. Therefore:

- **No backward compatibility needed** — no deprecation period, no dual-field support
- **Single atomic rename** — all changes land in one PR
- **No data migration** — EnvironmentConfigs in any existing dev clusters need
  their labels updated manually (`asya.sh/flavor` -> `asya.sh/overlay`), but
  there are no production deployments

### 7. Verification

After the rename, the following must pass:

1. `make build` — all components compile
2. `make test-unit` — all unit tests pass (Go + Python)
3. `make lint` — no lint errors
4. Grep verification — zero hits for "flavor" in active source/config:
   ```bash
   grep -ri "flavor" src/ deploy/ testing/ Makefile \
     --include="*.go" --include="*.py" --include="*.yaml" \
     --include="*.yml" --include="*.sh"
   ```
   (excludes closed aint files and CHANGELOG.md)

### 8. Task Breakdown

| # | Task | Scope |
|---|------|-------|
| 1 | Rename `src/function-asya-flavors/` directory to `src/function-asya-overlays/` | filesystem |
| 2 | Update Go source (`fn.go`, `merge.go`, `main.go`, `go.mod`) | Go |
| 3 | Update Go tests (`fn_test.go`, `merge_test.go`) | Go |
| 4 | Update Go Makefile (`src/function-asya-overlays/Makefile`) | build |
| 5 | Update XRD schema (`xrd-asyncactor.yaml`) | Helm |
| 6 | Update Compositions (`composition-sqs.yaml`, `composition-rabbitmq.yaml`) | Helm |
| 7 | Update providers template (`providers.yaml`) | Helm |
| 8 | Update Helm values (`values.yaml`) | Helm |
| 9 | Update E2E profiles, values, environment-configs, actor templates | test |
| 10 | Update E2E Python tests (`test_crossplane_e2e.py`) | test |
| 11 | Update root `Makefile` | build |
| 12 | Update `src/build-images.sh` | build |
| 13 | Update `.github/release-drafter.yml` | CI |
| 14 | Update `testing/e2e/scripts/deploy.sh` | test |
| 15 | Update open aint issues referencing flavors | docs |
| 16 | Update `AGENTS.md` example YAML | docs |
| 17 | Run `make build && make test-unit && make lint` | verification |
| 18 | Run grep verification (see section 7) | verification |
