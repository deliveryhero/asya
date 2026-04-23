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
It is bundled in the asya-crew image and invoked via command override.
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
Resolve image for DLQ worker — uses the shared asya-crew image.
The /dlq-worker binary is compiled into it; the Deployment overrides the command.
*/}}
{{- define "asya-crew.dlq-worker.image" -}}
{{- $global := .Values.image }}
{{- $tag := $global.tag | default .Chart.AppVersion }}
{{- printf "%s:%s" $global.repository $tag }}
{{- end }}

{{/*
Resolve image pull policy for DLQ worker
*/}}
{{- define "asya-crew.dlq-worker.imagePullPolicy" -}}
{{- .Values.image.pullPolicy | default "IfNotPresent" }}
{{- end }}

{{/*
Pub/Sub spec fields (no-op, gcpProject removed from XRD).
*/}}
{{- define "asya-crew.pubsub-spec" -}}
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
Persistence stateProxy spec (inline on AsyncActor, read by Crossplane composition from XR spec)
Call with bucket name override via dict: include "asya-crew.persistence.stateProxy" (dict "Values" .Values "Chart" .Chart "bucket" "my-bucket")
If "bucket" key is absent, falls back to .Values.persistence.config.bucket.
*/}}
{{- define "asya-crew.persistence.stateProxy" -}}
{{- $values := .Values }}
{{- $bucket := default $values.persistence.config.bucket .bucket }}
{{- $connectorImage := printf "%s:%s" $values.persistence.connector.image.repository ($values.persistence.connector.image.tag | default .Chart.AppVersion) }}
- name: checkpoints
  mount:
    path: /state/checkpoints
  connector:
    image: {{ $connectorImage }}
    env:
      - name: ASYA_CONNECTOR
        value: {{ if eq $values.persistence.backend "s3" }}s3_buffered_lww{{ else }}gcs_buffered_lww{{ end }}
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
