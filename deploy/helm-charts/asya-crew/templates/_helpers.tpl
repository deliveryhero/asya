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
Common labels for x-sink actor
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-crew.x-sink.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
asya.sh/actor: x-sink
{{- end }}

{{/*
Common labels for x-sump actor
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-crew.x-sump.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
asya.sh/actor: x-sump
{{- end }}

{{/*
Common labels for checkpoint-s3 actor
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-crew.checkpoint-s3.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
asya.sh/actor: checkpoint-s3
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
Resolve image for x-sink actor (convenience wrapper)
*/}}
{{- define "asya-crew.x-sink.image" -}}
{{- include "asya-crew.actor.image" (dict "root" . "actorName" "x-sink") }}
{{- end }}

{{/*
Resolve image pull policy for x-sink actor (convenience wrapper)
*/}}
{{- define "asya-crew.x-sink.imagePullPolicy" -}}
{{- include "asya-crew.actor.imagePullPolicy" (dict "root" . "actorName" "x-sink") }}
{{- end }}

{{/*
Resolve image for x-sump actor (convenience wrapper)
*/}}
{{- define "asya-crew.x-sump.image" -}}
{{- include "asya-crew.actor.image" (dict "root" . "actorName" "x-sump") }}
{{- end }}

{{/*
Resolve image pull policy for x-sump actor (convenience wrapper)
*/}}
{{- define "asya-crew.x-sump.imagePullPolicy" -}}
{{- include "asya-crew.actor.imagePullPolicy" (dict "root" . "actorName" "x-sump") }}
{{- end }}

{{/*
Resolve image for checkpoint-s3 actor (convenience wrapper)
*/}}
{{- define "asya-crew.checkpoint-s3.image" -}}
{{- include "asya-crew.actor.image" (dict "root" . "actorName" "checkpoint-s3") }}
{{- end }}

{{/*
Resolve image pull policy for checkpoint-s3 actor (convenience wrapper)
*/}}
{{- define "asya-crew.checkpoint-s3.imagePullPolicy" -}}
{{- include "asya-crew.actor.imagePullPolicy" (dict "root" . "actorName" "checkpoint-s3") }}
{{- end }}

{{/*
Common labels for x-pause actor
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-crew.x-pause.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
asya.sh/actor: x-pause
{{- end }}

{{/*
Common labels for x-resume actor
Labels for AsyncActor CRs should NOT include reserved prefixes (app.kubernetes.io/, etc.)
as these are managed by the operator and added to child resources.
*/}}
{{- define "asya-crew.x-resume.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
asya.sh/actor: x-resume
{{- end }}

{{/*
Resolve image for x-pause actor (convenience wrapper)
*/}}
{{- define "asya-crew.x-pause.image" -}}
{{- include "asya-crew.actor.image" (dict "root" . "actorName" "x-pause") }}
{{- end }}

{{/*
Resolve image pull policy for x-pause actor (convenience wrapper)
*/}}
{{- define "asya-crew.x-pause.imagePullPolicy" -}}
{{- include "asya-crew.actor.imagePullPolicy" (dict "root" . "actorName" "x-pause") }}
{{- end }}

{{/*
Resolve image for x-resume actor (convenience wrapper)
*/}}
{{- define "asya-crew.x-resume.image" -}}
{{- include "asya-crew.actor.image" (dict "root" . "actorName" "x-resume") }}
{{- end }}

{{/*
Resolve image pull policy for x-resume actor (convenience wrapper)
*/}}
{{- define "asya-crew.x-resume.imagePullPolicy" -}}
{{- include "asya-crew.actor.imagePullPolicy" (dict "root" . "actorName" "x-resume") }}
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

{{/*
Pub/Sub spec fields (gcpProject). Include in AsyncActor spec when gcpProject is set.
*/}}
{{- define "asya-crew.pubsub-spec" -}}
{{- if .Values.gcpProject }}
gcpProject: {{ .Values.gcpProject }}
{{- end }}
{{- end }}

{{/*
Persistence flavor name
*/}}
{{- define "asya-crew.persistence.flavorName" -}}
{{- printf "%s-persistence-%s" .Release.Name .Values.persistence.backend }}
{{- end }}

{{/*
Persistence flavor labels
*/}}
{{- define "asya-crew.persistence.labels" -}}
helm.sh/chart: {{ include "asya-crew.chart" . }}
{{- end }}

{{/*
Persistence stateProxy spec (inline on AsyncActor, bypasses EnvironmentConfig flavor)
Call with bucket name override via dict: include "asya-crew.persistence.stateProxy" (dict "Values" .Values "bucket" "my-bucket")
If "bucket" key is absent, falls back to .Values.persistence.config.bucket.
*/}}
{{- define "asya-crew.persistence.stateProxy" -}}
{{- $values := .Values }}
{{- $bucket := default $values.persistence.config.bucket .bucket }}
{{- $connectorImage := dict "val" $values.persistence.connector.image }}
{{- if not $connectorImage.val }}
  {{- if eq $values.persistence.backend "s3" }}
    {{- $_ := set $connectorImage "val" "ghcr.io/deliveryhero/asya-state-proxy-s3-buffered-lww:v1.0.0" }}
  {{- else if eq $values.persistence.backend "gcs" }}
    {{- $_ := set $connectorImage "val" "ghcr.io/deliveryhero/asya-state-proxy-gcs-buffered-lww:v1.0.0" }}
  {{- end }}
{{- end }}
- name: checkpoints
  mount:
    path: /state/checkpoints
  connector:
    image: {{ $connectorImage.val }}
    env:
      - name: STATE_BUCKET
        value: {{ $bucket | quote }}
      {{- if eq $values.persistence.backend "s3" }}
      {{- with $values.persistence.config.endpoint }}
      - name: AWS_ENDPOINT_URL
        value: {{ . | quote }}
      {{- end }}
      {{- with $values.persistence.config.region }}
      - name: AWS_REGION
        value: {{ . | quote }}
      {{- end }}
      {{- with $values.persistence.config.accessKey }}
      - name: AWS_ACCESS_KEY_ID
        value: {{ . | quote }}
      {{- end }}
      {{- with $values.persistence.config.secretKey }}
      - name: AWS_SECRET_ACCESS_KEY
        value: {{ . | quote }}
      {{- end }}
      {{- else if eq $values.persistence.backend "gcs" }}
      {{- with $values.persistence.config.project }}
      - name: GCS_PROJECT
        value: {{ . | quote }}
      {{- end }}
      {{- with $values.persistence.config.emulatorHost }}
      - name: STORAGE_EMULATOR_HOST
        value: {{ . | quote }}
      {{- end }}
      {{- end }}
{{- end }}
