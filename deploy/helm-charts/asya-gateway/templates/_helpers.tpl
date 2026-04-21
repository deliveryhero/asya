{{/*
Expand the name of the chart.
*/}}
{{- define "asya-gateway.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "asya-gateway.fullname" -}}
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
{{- define "asya-gateway.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "asya-gateway.labels" -}}
helm.sh/chart: {{ include "asya-gateway.chart" . }}
{{ include "asya-gateway.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "asya-gateway.selectorLabels" -}}
app.kubernetes.io/name: {{ include "asya-gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "asya-gateway.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "asya-gateway.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Validate transport configuration - ensure exactly one transport is enabled
*/}}
{{- define "asya-gateway.validateTransports" -}}
{{- $rabbitmqEnabled := .Values.transports.rabbitmq.enabled }}
{{- $sqsEnabled := .Values.transports.sqs.enabled }}
{{- $pubsubEnabled := ((.Values.transports).pubsub).enabled | default false }}
{{- $enabledCount := (list $rabbitmqEnabled $sqsEnabled $pubsubEnabled) | compact | len }}
{{- if gt $enabledCount 1 }}
{{- fail "ERROR: Cannot enable multiple transports. Please set exactly one of transports.rabbitmq.enabled, transports.sqs.enabled, or transports.pubsub.enabled to true" }}
{{- end }}
{{- if eq $enabledCount 0 }}
{{- fail "ERROR: No transport enabled. Please set one of transports.rabbitmq.enabled, transports.sqs.enabled, or transports.pubsub.enabled to true" }}
{{- end }}
{{- end }}

{{/*
Fully qualified name for the mesh-api service (external).
*/}}
{{- define "asya-gateway.meshApi.fullname" -}}
{{- printf "%s-mesh-api" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified name for the mesh-api internal service (sidecar callbacks).
*/}}
{{- define "asya-gateway.meshApiInt.fullname" -}}
{{- printf "%s-mesh-api-int" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified name for the MCP adapter service.
*/}}
{{- define "asya-gateway.mcp.fullname" -}}
{{- printf "%s-mcp" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified name for the A2A adapter service.
*/}}
{{- define "asya-gateway.a2a.fullname" -}}
{{- printf "%s-a2a" (include "asya-gateway.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Internal mesh-api service URL (for x-asya-gateway-url header).
Sidecar callbacks use this URL via the envelope header.
*/}}
{{- define "asya-gateway.internalURL" -}}
http://{{ include "asya-gateway.meshApiInt.fullname" . }}.{{ .Release.Namespace }}.svc.cluster.local:{{ .Values.service.meshApiInternal.port }}
{{- end }}
