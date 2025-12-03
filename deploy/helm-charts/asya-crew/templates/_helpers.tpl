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
