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
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-crew.happy-end.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
asya.sh/actor: happy-end
{{- end }}

{{/*
Common labels for error-end actor
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-crew.error-end.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
asya.sh/actor: error-end
{{- end }}

{{/*
Generic image resolver for any actor
Takes a dict with keys: root (template root context), actorName (string)
Returns fully qualified image with tag
*/}}
{{- define "asya-crew.actor.image" -}}
{{- $global := .root.Values.image }}
{{- $actor := index .root.Values .actorName }}
{{- $repository := $actor.image.repository | default $global.repository }}
{{- $tag := $actor.image.tag | default ($global.tag | default .root.Chart.AppVersion) }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}

{{/*
Generic image pull policy resolver for any actor
Takes a dict with keys: root (template root context), actorName (string)
Returns image pull policy
*/}}
{{- define "asya-crew.actor.imagePullPolicy" -}}
{{- $global := .root.Values.image }}
{{- $actor := index .root.Values .actorName }}
{{- $actor.image.pullPolicy | default $global.pullPolicy }}
{{- end }}

{{/*
Resolve image for happy-end actor (convenience wrapper)
*/}}
{{- define "asya-crew.happy-end.image" -}}
{{- include "asya-crew.actor.image" (dict "root" . "actorName" "happy-end") }}
{{- end }}

{{/*
Resolve image pull policy for happy-end actor (convenience wrapper)
*/}}
{{- define "asya-crew.happy-end.imagePullPolicy" -}}
{{- include "asya-crew.actor.imagePullPolicy" (dict "root" . "actorName" "happy-end") }}
{{- end }}

{{/*
Resolve image for error-end actor (convenience wrapper)
*/}}
{{- define "asya-crew.error-end.image" -}}
{{- include "asya-crew.actor.image" (dict "root" . "actorName" "error-end") }}
{{- end }}

{{/*
Resolve image pull policy for error-end actor (convenience wrapper)
*/}}
{{- define "asya-crew.error-end.imagePullPolicy" -}}
{{- include "asya-crew.actor.imagePullPolicy" (dict "root" . "actorName" "error-end") }}
{{- end }}

{{/*
DLQ Worker helpers
The DLQ worker is a standalone Go binary (NOT an AsyncActor).
It uses a separate image (asya-dlq-worker) with its own image config.
*/}}

{{/*
Full name for the DLQ worker deployment
*/}}
{{- define "asya-crew.dlq-worker.fullname" -}}
{{- printf "%s-dlq-worker" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Labels for DLQ worker
*/}}
{{- define "asya-crew.dlq-worker.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
{{ include "asya-crew.dlq-worker.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels for DLQ worker
*/}}
{{- define "asya-crew.dlq-worker.selectorLabels" -}}
app.kubernetes.io/name: dlq-worker
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: crew
{{- end }}

{{/*
Resolve image for DLQ worker
Uses dlq-worker.image config (separate from the crew actor images)
*/}}
{{- define "asya-crew.dlq-worker.image" -}}
{{- $dlq := index .Values "dlq-worker" }}
{{- $repository := $dlq.image.repository | default "ghcr.io/deliveryhero/asya-dlq-worker" }}
{{- $tag := $dlq.image.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}

{{/*
Resolve image pull policy for DLQ worker
*/}}
{{- define "asya-crew.dlq-worker.imagePullPolicy" -}}
{{- $dlq := index .Values "dlq-worker" }}
{{- $dlq.image.pullPolicy | default "IfNotPresent" }}
{{- end }}
