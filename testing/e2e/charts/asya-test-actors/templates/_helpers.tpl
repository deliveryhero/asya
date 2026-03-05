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
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-test-actors.labels" -}}
helm.sh/chart: {{ include "asya-test-actors.chart" . }}
{{- with .Values.labels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Pub/Sub spec fields (gcpProject). Include in AsyncActor spec when transport is pubsub.
*/}}
{{- define "asya-test-actors.pubsub-spec" -}}
{{- if and (eq .Values.transport "pubsub") .Values.gcpProject }}
gcpProject: {{ .Values.gcpProject }}
{{- end }}
{{- end }}
