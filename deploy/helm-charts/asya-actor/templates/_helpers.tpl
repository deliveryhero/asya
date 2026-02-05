{{/*
Expand the name of the chart.
*/}}
{{- define "asya-actor.name" -}}
{{- .Values.name | default .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "asya-actor.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "asya-actor.labels" -}}
helm.sh/chart: {{ include "asya-actor.chart" . }}
{{ include "asya-actor.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "asya-actor.selectorLabels" -}}
app.kubernetes.io/name: {{ include "asya-actor.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
