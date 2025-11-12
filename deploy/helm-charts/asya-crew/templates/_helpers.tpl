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
*/}}
{{- define "asya-crew.happy-end.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
app.kubernetes.io/name: {{ include "asya-crew.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: happy-end
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
actor: happy-end
{{- end }}

{{/*
Common labels for error-end actor
*/}}
{{- define "asya-crew.error-end.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
app.kubernetes.io/name: {{ include "asya-crew.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: error-end
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
actor: error-end
{{- end }}
