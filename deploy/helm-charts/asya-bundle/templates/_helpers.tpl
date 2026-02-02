{{/*
Configure transport settings based on global.transport and global.profile
*/}}
{{- define "asya-bundle.transport.rabbitmq.enabled" -}}
{{- if eq .Values.global.transport "rabbitmq" }}true{{ else }}false{{ end -}}
{{- end -}}

{{- define "asya-bundle.transport.sqs.enabled" -}}
{{- if eq .Values.global.transport "sqs" }}true{{ else }}false{{ end -}}
{{- end -}}

{{/*
Configure storage settings based on global.storage and global.profile
*/}}
{{- define "asya-bundle.storage.s3.enabled" -}}
{{- if eq .Values.global.storage "s3" }}true{{ else }}false{{ end -}}
{{- end -}}

{{- define "asya-bundle.storage.minio.enabled" -}}
{{- if eq .Values.global.storage "minio" }}true{{ else }}false{{ end -}}
{{- end -}}

{{/*
Determine infrastructure components based on profile
*/}}
{{- define "asya-bundle.localstack.shouldEnable" -}}
{{- if and (eq .Values.global.profile "local") (or (eq .Values.global.transport "sqs") (eq .Values.global.storage "s3")) }}true{{ else }}false{{ end -}}
{{- end -}}

{{- define "asya-bundle.rabbitmq.shouldEnable" -}}
{{- if and (eq .Values.global.profile "local") (eq .Values.global.transport "rabbitmq") }}true{{ else }}false{{ end -}}
{{- end -}}

{{- define "asya-bundle.minio.shouldEnable" -}}
{{- if and (eq .Values.global.profile "local") (eq .Values.global.storage "minio") }}true{{ else }}false{{ end -}}
{{- end -}}

{{/*
Gateway URL for operator
*/}}
{{- define "asya-bundle.gatewayURL" -}}
{{- if .Values.gateway.enabled -}}
http://asya-gateway.{{ .Release.Namespace }}.svc.cluster.local:80
{{- end -}}
{{- end -}}

{{/*
Transport configuration for gateway
*/}}
{{- define "asya-bundle.gateway.rabbitmqURL" -}}
{{- if eq .Values.global.transport "rabbitmq" -}}
amqp://{{ .Values.rabbitmq.auth.username }}:{{ .Values.rabbitmq.auth.password }}@rabbitmq.{{ .Release.Namespace }}.svc.cluster.local:5672/
{{- end -}}
{{- end -}}

{{- define "asya-bundle.gateway.sqsEndpoint" -}}
{{- if and (eq .Values.global.transport "sqs") (eq .Values.global.profile "local") -}}
http://localstack.{{ .Release.Namespace }}:4566
{{- end -}}
{{- end -}}

{{- define "asya-bundle.gateway.sqsRegion" -}}
{{- if eq .Values.global.transport "sqs" -}}
us-east-1
{{- end -}}
{{- end -}}
