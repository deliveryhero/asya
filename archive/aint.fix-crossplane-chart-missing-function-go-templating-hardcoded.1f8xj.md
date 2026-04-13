---
title: "Fix Crossplane chart: missing function-go-templating + hardcoded serviceAccountName"
status: merged
priority: 1
tags:
  - type:bug
---

Two bugs discovered during Phase 3.5 lifecycle testing:

## Bug 1: Missing function-go-templating provider

**File**: deploy/helm-charts/asya-crossplane/templates/providers.yaml
**Problem**: The composition-sqs.yaml references function-go-templating in 6 pipeline steps (render-sqs-queue, render-serviceaccount, render-triggerauthentication, render-scaledobject, render-deployment, derive-phase) but providers.yaml only installs function-patch-and-transform.
**Fix**:
1. Add Function resource to providers.yaml:
   apiVersion: pkg.crossplane.io/v1
   kind: Function
   name: function-go-templating
   package: xpkg.upbound.io/crossplane-contrib/function-go-templating:{{ .Values.functions.goTemplatingVersion }}
2. Add goTemplatingVersion to values.yaml functions section

## Bug 2: serviceAccountName hardcoded when IRSA disabled

**File**: deploy/helm-charts/asya-crossplane/templates/composition-sqs.yaml (line 329)
**Problem**: serviceAccountName: {{ .Values.irsa.serviceAccountName }} is always rendered (Helm-time, not Go-template-time) even when irsa.enabled=false (LocalStack mode). No ServiceAccount is created when IRSA is disabled, but Deployment references it -> pods fail.
**Fix**: Wrap in Helm conditional:
  {{- if .Values.irsa.enabled }}
  serviceAccountName: {{ .Values.irsa.serviceAccountName }}
  {{- end }}


---
**Close reason**: Fixed: Added function-go-templating Function resource to providers.yaml and goTemplatingVersion to values.yaml. Wrapped serviceAccountName in IRSA conditional.


---
_Migrated from beads `asya-w1l`_
