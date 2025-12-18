{{/*
Expand the name of the chart.
*/}}
{{- define "poundcake.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "poundcake.fullname" -}}
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
{{- define "poundcake.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "poundcake.labels" -}}
helm.sh/chart: {{ include "poundcake.chart" . }}
{{ include "poundcake.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "poundcake.selectorLabels" -}}
app.kubernetes.io/name: {{ include "poundcake.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "poundcake.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "poundcake.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Get the secret name for StackStorm credentials
*/}}
{{- define "poundcake.stackstormSecretName" -}}
{{- if .Values.stackstorm.existingSecret }}
{{- .Values.stackstorm.existingSecret }}
{{- else }}
{{- include "poundcake.fullname" . }}-stackstorm
{{- end }}
{{- end }}

{{/*
Get the secret name for Redis credentials
*/}}
{{- define "poundcake.redisSecretName" -}}
{{- if .Values.redis.existingSecret }}
{{- .Values.redis.existingSecret }}
{{- else if and (not .Values.redis.deploy) .Values.redis.external.existingSecret }}
{{- .Values.redis.external.existingSecret }}
{{- else }}
{{- include "poundcake.fullname" . }}-redis
{{- end }}
{{- end }}

{{/*
Get the Redis URL
*/}}
{{- define "poundcake.redisUrl" -}}
{{- if .Values.redis.deploy }}
{{- printf "redis://%s-redis:6379/0" (include "poundcake.fullname" .) }}
{{- else }}
{{- .Values.redis.external.url }}
{{- end }}
{{- end }}

{{/*
Get the secret name for Git credentials
*/}}
{{- define "poundcake.gitSecretName" -}}
{{- if .Values.git.existingSecret }}
{{- .Values.git.existingSecret }}
{{- else }}
{{- include "poundcake.fullname" . }}-git
{{- end }}
{{- end }}
