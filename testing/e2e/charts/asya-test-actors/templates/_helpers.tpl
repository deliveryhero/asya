{{/*
Expand the name of the chart.
*/}}
{{- define "asya-test-actors.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "asya-test-actors.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "asya-test-actors.labels" -}}
helm.sh/chart: {{ include "asya-test-actors.chart" . }}
{{ include "asya-test-actors.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.labels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "asya-test-actors.selectorLabels" -}}
app.kubernetes.io/name: {{ include "asya-test-actors.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
