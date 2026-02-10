{{/*
Expand the name of the chart.
*/}}
{{- define "asya-injector.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "asya-injector.fullname" -}}
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
{{- define "asya-injector.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "asya-injector.labels" -}}
helm.sh/chart: {{ include "asya-injector.chart" . }}
{{ include "asya-injector.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: asya
{{- end }}

{{/*
Selector labels
*/}}
{{- define "asya-injector.selectorLabels" -}}
app.kubernetes.io/name: {{ include "asya-injector.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "asya-injector.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "asya-injector.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Certificate name
*/}}
{{- define "asya-injector.certificateName" -}}
{{- include "asya-injector.fullname" . }}-tls
{{- end }}

{{/*
Secret name for TLS certificate
*/}}
{{- define "asya-injector.tlsSecretName" -}}
{{- include "asya-injector.fullname" . }}-tls
{{- end }}

{{/*
Service DNS name
*/}}
{{- define "asya-injector.serviceDNS" -}}
{{- include "asya-injector.fullname" . }}.{{ .Release.Namespace }}.svc
{{- end }}
