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
Pub/Sub spec fields. gcpProject is now platform config set via EnvironmentConfig,
not an AsyncActor spec field. This helper is kept for backward compatibility but
renders nothing.
*/}}
{{- define "asya-test-actors.pubsub-spec" -}}
{{- end }}
