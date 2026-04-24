{{/*
Expand the name of the chart.
*/}}
{{- define "asya-loadtest.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "asya-loadtest.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "asya-loadtest.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "asya-loadtest.labels" -}}
helm.sh/chart: {{ include "asya-loadtest.chart" . }}
{{ include "asya-loadtest.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "asya-loadtest.selectorLabels" -}}
app.kubernetes.io/name: {{ include "asya-loadtest.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Resolve the workload image (tag defaults to Chart.AppVersion).
*/}}
{{- define "asya-loadtest.image" -}}
{{ .Values.workload.image.repository }}:{{ .Values.workload.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Compute the list of enabled scenario names.
*/}}
{{- define "asya-loadtest.enabledScenarios" -}}
{{- $scenarios := list -}}
{{- range $name, $cfg := .Values.scenarios -}}
  {{- if $cfg.enabled -}}
    {{- $scenarios = append $scenarios $name -}}
  {{- end -}}
{{- end -}}
{{- $scenarios | toJson }}
{{- end }}

{{/*
Build the ASYA_SCENARIOS JSON value (list of {actor, payload} objects for all enabled scenarios).
*/}}
{{- define "asya-loadtest.scenariosJson" -}}
{{- $list := list -}}
{{- range $name, $cfg := .Values.scenarios -}}
  {{- if $cfg.enabled -}}
    {{- $list = append $list (dict "actor" (printf "loadtest-%s" $name) "payload" (dict)) -}}
  {{- end -}}
{{- end -}}
{{- $list | toJson }}
{{- end }}

{{/*
Resolve the queue prefix for transport mode.
Defaults to "asya-{namespace}-" when not set.
*/}}
{{- define "asya-loadtest.queuePrefix" -}}
{{- if .Values.target.transport.queuePrefix -}}
  {{- .Values.target.transport.queuePrefix -}}
{{- else -}}
  {{- printf "asya-%s-" .Release.Namespace -}}
{{- end -}}
{{- end }}

{{/*
Resolve the k6 target URL based on mode.
*/}}
{{- define "asya-loadtest.targetUrl" -}}
{{- if eq .Values.mode "mesh-api" -}}
  {{- required "target.mesh.url is required for mesh-api mode" .Values.target.mesh.url -}}
{{- else if eq .Values.mode "a2a" -}}
  {{- required "target.a2a.url is required for a2a mode" .Values.target.a2a.url -}}
{{- else if eq .Values.mode "mcp" -}}
  {{- required "target.mcp.url is required for mcp mode" .Values.target.mcp.url -}}
{{- else -}}
  {{- "" -}}
{{- end -}}
{{- end }}

{{/*
ServiceAccount name.
*/}}
{{- define "asya-loadtest.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
  {{- include "asya-loadtest.fullname" . }}
{{- else -}}
  default
{{- end -}}
{{- end }}
