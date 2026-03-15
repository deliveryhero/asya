{{/*
Namespace helpers - resolve namespace with fallback to release namespace
*/}}
{{- define "asya-playground.namespace.monitoring" -}}
{{- if .Values.namespaces.monitoring -}}
{{ .Values.namespaces.monitoring }}
{{- else -}}
{{ .Release.Namespace }}
{{- end -}}
{{- end -}}

{{- define "asya-playground.namespace.infra" -}}
{{- if .Values.namespaces.infra -}}
{{ .Values.namespaces.infra }}
{{- else -}}
{{ .Release.Namespace }}
{{- end -}}
{{- end -}}

{{/*
Configure transport settings based on global.transport and global.profile
*/}}
{{- define "asya-playground.transport.rabbitmq.enabled" -}}
{{- if eq .Values.global.transport "rabbitmq" }}true{{ else }}false{{ end -}}
{{- end -}}

{{- define "asya-playground.transport.sqs.enabled" -}}
{{- if eq .Values.global.transport "sqs" }}true{{ else }}false{{ end -}}
{{- end -}}

{{/*
Configure storage settings based on global.storage and global.profile
*/}}
{{- define "asya-playground.storage.s3.enabled" -}}
{{- if eq .Values.global.storage "s3" }}true{{ else }}false{{ end -}}
{{- end -}}

{{- define "asya-playground.storage.minio.enabled" -}}
{{- if eq .Values.global.storage "minio" }}true{{ else }}false{{ end -}}
{{- end -}}

{{/*
Determine sample infrastructure components based on transport and storage
*/}}
{{- define "asya-playground.transport.sqs.endpoint" -}}
{{- if and (eq .Values.global.transport "sqs") (eq .Values.global.profile "local") -}}
http://localstack-sqs.{{ include "asya-playground.namespace.infra" . }}:4566
{{- end -}}
{{- end -}}

{{- define "asya-playground.storage.s3.endpoint" -}}
{{- if and (eq .Values.global.storage "s3") (eq .Values.global.profile "local") -}}
http://s3-localstack.{{ include "asya-playground.namespace.infra" . }}:4566
{{- end -}}
{{- end -}}

{{/*
Gateway URL for crew actors and sidecar configuration
*/}}
{{- define "asya-playground.gatewayURL" -}}
{{- if (index .Values "asya-gateway").enabled -}}
http://asya-gateway.{{ .Release.Namespace }}.svc.cluster.local:80
{{- end -}}
{{- end -}}

{{/*
Transport configuration for gateway
*/}}
{{- define "asya-playground.gateway.rabbitmqURL" -}}
{{- if eq .Values.global.transport "rabbitmq" -}}
amqp://{{ .Values.sampleTransport.rabbitmq.auth.username }}:{{ .Values.sampleTransport.rabbitmq.auth.password }}@rabbitmq.{{ include "asya-playground.namespace.infra" . }}.svc.cluster.local:5672/
{{- end -}}
{{- end -}}

{{- define "asya-playground.gateway.sqsEndpoint" -}}
{{- if and (eq .Values.global.transport "sqs") (eq .Values.global.profile "local") -}}
http://localstack-sqs.{{ include "asya-playground.namespace.infra" . }}:4566
{{- end -}}
{{- end -}}

{{- define "asya-playground.gateway.sqsRegion" -}}
{{- if eq .Values.global.transport "sqs" -}}
us-east-1
{{- end -}}
{{- end -}}

{{/*
Prometheus remote write URL for k6 and other tools
*/}}
{{- define "asya-playground.prometheus.remoteWriteUrl" -}}
http://asya-monitoring-prometheus.{{ include "asya-playground.namespace.monitoring" . }}:9090/api/v1/write
{{- end -}}
