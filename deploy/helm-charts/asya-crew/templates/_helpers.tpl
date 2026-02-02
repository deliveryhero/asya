{{/*
Expand the name of the chart.
*/}}
{{- define "asya-crew.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "asya-crew.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels for happy-end actor
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-crew.happy-end.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
actor: happy-end
{{- end }}

{{/*
Common labels for error-end actor
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-crew.error-end.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
actor: error-end
{{- end }}

{{/*
Resolve image for happy-end actor
Uses actor-specific config, falls back to global config, defaults tag to Chart.AppVersion
*/}}
{{- define "asya-crew.happy-end.image" -}}
{{- $global := .Values.image }}
{{- $actor := index .Values "happy-end" }}
{{- $repository := $actor.image.repository | default $global.repository }}
{{- $tag := $actor.image.tag | default ($global.tag | default .Chart.AppVersion) }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}

{{/*
Resolve image pull policy for happy-end actor
*/}}
{{- define "asya-crew.happy-end.imagePullPolicy" -}}
{{- $global := .Values.image }}
{{- $actor := index .Values "happy-end" }}
{{- $actor.image.pullPolicy | default $global.pullPolicy }}
{{- end }}

{{/*
Resolve image for error-end actor
Uses actor-specific config, falls back to global config, defaults tag to Chart.AppVersion
*/}}
{{- define "asya-crew.error-end.image" -}}
{{- $global := .Values.image }}
{{- $actor := index .Values "error-end" }}
{{- $repository := $actor.image.repository | default $global.repository }}
{{- $tag := $actor.image.tag | default ($global.tag | default .Chart.AppVersion) }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}

{{/*
Resolve image pull policy for error-end actor
*/}}
{{- define "asya-crew.error-end.imagePullPolicy" -}}
{{- $global := .Values.image }}
{{- $actor := index .Values "error-end" }}
{{- $actor.image.pullPolicy | default $global.pullPolicy }}
{{- end }}
