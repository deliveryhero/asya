---
title: Add Helm chart version constraint validation
status: merged
priority: 2
---

## Problem

Asya components (operator, sidecars, gateway, crew) must be version-aligned to work correctly. Currently:
- Operator injects sidecar images (must match operator version)
- Gateway communicates with actors via sidecars (protocol compatibility)
- Crew actors use runtime that matches operator-injected runtime

No validation exists to prevent version mismatches during Helm installation.

## Goal

Add version constraint validation to Helm charts to ensure compatibility:
1. Gateway version >= Operator version (gateway must support operator's protocol)
2. Crew version == Operator version (uses same runtime/sidecar)
3. Sidecar image tag == Operator version (operator controls injection)

## Implementation

### 1. Operator Chart Validation

Add validation helper in `deploy/helm-charts/asya-operator/templates/_helpers.tpl`:

```yaml
{{- define "asya-operator.validateVersions" -}}
{{- $operatorVersion := .Chart.Version -}}
{{- $sidecarTag := .Values.sidecar.image.tag | default .Chart.AppVersion -}}
{{- if ne $sidecarTag $operatorVersion -}}
{{- fail (printf "Sidecar image tag (%s) must match operator version (%s)" $sidecarTag $operatorVersion) -}}
{{- end -}}
{{- end -}}
```

Use in `templates/deployment.yaml`:
```yaml
{{- include "asya-operator.validateVersions" . -}}
```

### 2. Gateway Chart Validation

Add validation in `deploy/helm-charts/asya-gateway/templates/_helpers.tpl`:

```yaml
{{- define "asya-gateway.validateOperatorVersion" -}}
{{- if .Values.operatorVersion -}}
{{- $gatewayVersion := .Chart.Version -}}
{{- $operatorVersion := .Values.operatorVersion -}}
{{- if semverCompare (printf "< %s" $operatorVersion) $gatewayVersion -}}
{{- fail (printf "Gateway version (%s) must be >= operator version (%s)" $gatewayVersion $operatorVersion) -}}
{{- end -}}
{{- end -}}
{{- end -}}
```

**values.yaml**:
```yaml
# Optional: Operator version for validation
# If set, gateway version must be >= this version
operatorVersion: ""
```

### 3. Crew Chart Validation

Add validation in `deploy/helm-charts/asya-crew/templates/_helpers.tpl`:

```yaml
{{- define "asya-crew.validateOperatorVersion" -}}
{{- if .Values.operatorVersion -}}
{{- $crewVersion := .Chart.Version -}}
{{- $operatorVersion := .Values.operatorVersion -}}
{{- if ne $crewVersion $operatorVersion -}}
{{- fail (printf "Crew version (%s) must match operator version (%s)" $crewVersion $operatorVersion) -}}
{{- end -}}
{{- end -}}
{{- end -}}
```

### 4. Bundle Chart Validation

In `deploy/helm-charts/asya-bundle/templates/_helpers.tpl`:

```yaml
{{- define "asya-bundle.validateVersions" -}}
{{- $bundleVersion := .Chart.Version -}}
{{- range .Chart.Dependencies -}}
{{- if eq .Name "asya-operator" "asya-gateway" "asya-crew" -}}
{{- if ne .Version $bundleVersion -}}
{{- fail (printf "Component %s version (%s) must match bundle version (%s)" .Name .Version $bundleVersion) -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- end -}}
```

Call in bundle's main template or NOTES.txt pre-install.

### 5. Documentation

Update chart READMEs to document version requirements:

**deploy/helm-charts/asya-operator/README.md**:
```markdown
## Version Compatibility

- Sidecar image tag MUST match operator version
- Gateway version MUST be >= operator version
- Crew version MUST match operator version
```

**deploy/helm-charts/asya-bundle/README.md**:
```markdown
## Version Constraints

All Asya components are version-locked:
- Operator: {{ .Chart.Version }}
- Gateway: {{ .Chart.Version }}
- Crew: {{ .Chart.Version }}
- Sidecar: {{ .Chart.AppVersion }}

Do not mix versions across components.
```

## Testing

1. Test operator with mismatched sidecar:
   ```bash
   helm template asya-operator deploy/helm-charts/asya-operator/ \
     --set sidecar.image.tag=0.2.0 \
     --set image.tag=0.3.0
   # Should fail with version mismatch error
   ```

2. Test gateway with old operator:
   ```bash
   helm template asya-gateway deploy/helm-charts/asya-gateway/ \
     --set operatorVersion=0.3.0 \
     --version 0.2.0
   # Should fail with version constraint error
   ```

3. Test bundle with mismatched dependencies:
   ```bash
   # Manually edit Chart.yaml to mismatch versions
   helm template asya-bundle deploy/helm-charts/asya-bundle/
   # Should fail with component version mismatch
   ```

## Acceptance Criteria

- [ ] Operator chart validates sidecar image tag matches operator version
- [ ] Gateway chart validates it's >= operator version (when operatorVersion set)
- [ ] Crew chart validates it matches operator version (when operatorVersion set)
- [ ] Bundle chart validates all components have matching versions
- [ ] Chart READMEs document version constraints
- [ ] Tests verify validation failures on version mismatches
- [ ] Validation helpers added to _helpers.tpl files
- [ ] values.yaml includes operatorVersion field (where needed)

## References

- Helm semver functions: https://helm.sh/docs/chart_template_guide/function_list/#semver-functions
- Chart version constraints: https://helm.sh/docs/topics/charts/#chart-dependencies


---
**Close reason**: Implemented version validation across all Helm charts. PR: https://github.com/deliveryhero/asya/pull/121


---
_Migrated from beads `asya-74o`_
