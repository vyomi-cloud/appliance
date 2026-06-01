"""Tier-feature implementation: helm chart + air-gapped install (Enterprise).

Generates a real Helm chart for the CloudLearn simulator deployment.
Endpoints serve:
  GET /api/runtime/helm/chart.tar.gz   → tarball of the chart
  GET /api/runtime/helm/values.yaml    → default values
  GET /api/runtime/helm/airgap-bundle.tar.gz → chart + image manifests + install.sh

The chart targets k8s 1.24+ and assumes the user runs:
   helm upgrade --install cloudlearn ./cloudlearn-chart -n cloudlearn --create-namespace
"""
from __future__ import annotations

import io
import tarfile
import time
from typing import Any


CHART_VERSION = "1.0.0"
APP_VERSION = "1.0.0"


def _chart_yaml(name: str = "cloudlearn") -> str:
    return f"""\
apiVersion: v2
name: {name}
description: CloudLearn multi-cloud simulator — local-fidelity AWS/GCP/Azure
type: application
version: {CHART_VERSION}
appVersion: "{APP_VERSION}"
keywords:
  - cloud
  - simulator
  - aws
  - gcp
  - azure
home: https://cloudlearn.io
maintainers:
  - name: CloudLearn
    email: support@cloudlearn.io
"""


def _values_yaml() -> str:
    return """\
# Default values for CloudLearn simulator
replicaCount: 1

image:
  repository: cloudlearn/simulator
  pullPolicy: IfNotPresent
  tag: "latest"

service:
  type: ClusterIP
  port: 9000

ingress:
  enabled: false
  className: "nginx"
  annotations: {}
  hosts:
    - host: cloudlearn.local
      paths:
        - path: /
          pathType: Prefix
  tls: []

resources:
  limits:
    cpu: 4
    memory: 4Gi
  requests:
    cpu: 1
    memory: 1Gi

persistence:
  enabled: true
  size: 10Gi
  storageClass: ""

config:
  # Pre-seeded license (optional). Leave empty to start on Free tier.
  license_tier: "free"
  # Disable host-budget enforcement (containers run in a constrained pod)
  budget_bypass: true
  # Vault deployment mode:
  #   dev  — `-dev` flag, in-memory unseal (data lost on restart). For tests only.
  #   prod — file storage backend + init/unseal sidecar (production).
  vault_mode: "prod"
  # When vault_mode=prod, the init container writes the root token to a
  # shared emptyDir the simulator mounts.
  vault_init_image: "hashicorp/vault:1.15"

env: {}

nodeSelector: {}
tolerations: []
affinity: {}
"""


def _deployment_yaml() -> str:
    return """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "cloudlearn.fullname" . }}
  labels:
    {{- include "cloudlearn.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "cloudlearn.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "cloudlearn.selectorLabels" . | nindent 8 }}
    spec:
      containers:
        - name: simulator
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - name: http
              containerPort: 9000
              protocol: TCP
          livenessProbe:
            httpGet: { path: /healthz, port: http }
            initialDelaySeconds: 30
            periodSeconds: 30
          readinessProbe:
            httpGet: { path: /healthz, port: http }
            initialDelaySeconds: 5
            periodSeconds: 10
          env:
            - name: CLOUDLEARN_LICENSE_TIER
              value: {{ .Values.config.license_tier | quote }}
            - name: CLOUDLEARN_BUDGET_BYPASS
              value: {{ .Values.config.budget_bypass | quote }}
            {{- range $k, $v := .Values.env }}
            - name: {{ $k }}
              value: {{ $v | quote }}
            {{- end }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          volumeMounts:
            - name: data
              mountPath: /app/data
      volumes:
        - name: data
          {{- if .Values.persistence.enabled }}
          persistentVolumeClaim:
            claimName: {{ include "cloudlearn.fullname" . }}-data
          {{- else }}
          emptyDir: {}
          {{- end }}
"""


def _service_yaml() -> str:
    return """\
apiVersion: v1
kind: Service
metadata:
  name: {{ include "cloudlearn.fullname" . }}
  labels:
    {{- include "cloudlearn.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    {{- include "cloudlearn.selectorLabels" . | nindent 4 }}
"""


def _ingress_yaml() -> str:
    return """\
{{- if .Values.ingress.enabled -}}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "cloudlearn.fullname" . }}
  labels:
    {{- include "cloudlearn.labels" . | nindent 4 }}
  {{- with .Values.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  ingressClassName: {{ .Values.ingress.className }}
  rules:
    {{- range .Values.ingress.hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          {{- range .paths }}
          - path: {{ .path }}
            pathType: {{ .pathType }}
            backend:
              service:
                name: {{ include "cloudlearn.fullname" $ }}
                port:
                  number: {{ $.Values.service.port }}
          {{- end }}
    {{- end }}
{{- end }}
"""


def _pvc_yaml() -> str:
    return """\
{{- if .Values.persistence.enabled -}}
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "cloudlearn.fullname" . }}-data
  labels:
    {{- include "cloudlearn.labels" . | nindent 4 }}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: {{ .Values.persistence.size }}
  {{- if .Values.persistence.storageClass }}
  storageClassName: {{ .Values.persistence.storageClass }}
  {{- end }}
{{- end }}
"""


def _helpers_tpl() -> str:
    return """\
{{- define "cloudlearn.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "cloudlearn.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "cloudlearn.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "cloudlearn.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
"""


def _airgap_install_sh() -> str:
    return """\
#!/usr/bin/env bash
# CloudLearn air-gapped installer
# Untar this bundle, then run: ./install.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "==> Loading container images into local docker..."
for f in "$HERE"/images/*.tar; do
  [ -f "$f" ] && docker load -i "$f"
done

echo "==> Installing/upgrading Helm release 'cloudlearn'..."
helm upgrade --install cloudlearn "$HERE/chart" \\
  -n cloudlearn --create-namespace \\
  -f "$HERE/values.yaml"

echo "==> Done. Check: kubectl -n cloudlearn get pods"
"""


def _image_manifest() -> str:
    return """\
# Air-gapped image manifest. To pre-pull these images for the bundle, run on
# an internet-connected host:
#   for img in $(cat image-manifest.txt); do
#     docker pull "$img" && docker save "$img" -o "images/$(echo $img | tr / _).tar"
#   done
cloudlearn/simulator:latest
# Real-backend services used by CloudLearn:
hashicorp/vault:1.15
nats:2.10
minio/minio:RELEASE.2024-01-16T16-07-38Z
amazon/dynamodb-local:2.0
softwaremill/elasticmq:1.5.7
postgres:15-alpine
mysql:8.0
"""


def build_chart_tarball() -> bytes:
    """Return the chart packaged as `cloudlearn-<version>.tgz` (Helm standard
    naming). Caller serves with mime type application/gzip."""
    buf = io.BytesIO()
    files = {
        "cloudlearn/Chart.yaml":            _chart_yaml(),
        "cloudlearn/values.yaml":           _values_yaml(),
        "cloudlearn/templates/deployment.yaml": _deployment_yaml(),
        "cloudlearn/templates/service.yaml":    _service_yaml(),
        "cloudlearn/templates/ingress.yaml":    _ingress_yaml(),
        "cloudlearn/templates/pvc.yaml":        _pvc_yaml(),
        "cloudlearn/templates/_helpers.tpl":    _helpers_tpl(),
    }
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            info.mtime = int(time.time())
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def build_airgap_bundle() -> bytes:
    """Air-gapped install bundle: chart + image manifest + install.sh +
    a stub images/ dir the user fills with `docker save` outputs."""
    buf = io.BytesIO()
    chart_bytes = build_chart_tarball()
    files = {
        "cloudlearn-airgap/chart.tgz":          chart_bytes,
        "cloudlearn-airgap/values.yaml":        _values_yaml().encode("utf-8"),
        "cloudlearn-airgap/install.sh":         _airgap_install_sh().encode("utf-8"),
        "cloudlearn-airgap/image-manifest.txt": _image_manifest().encode("utf-8"),
        "cloudlearn-airgap/README.md": (
            "# CloudLearn Air-Gapped Install\n\n"
            "1. On an internet-connected host, run the commands in `image-manifest.txt` "
            "to pre-pull each container image and `docker save` it under `images/`.\n"
            "2. Transfer this whole directory to the air-gapped host.\n"
            "3. Run `./install.sh` (requires `docker` + `helm` + `kubectl` already installed).\n"
        ).encode("utf-8"),
    }
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            info = tarfile.TarInfo(name=path)
            info.size = len(content)
            info.mtime = int(time.time())
            info.mode = 0o755 if path.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def chart_metadata() -> dict:
    return {
        "name": "cloudlearn",
        "version": CHART_VERSION,
        "app_version": APP_VERSION,
        "files": [
            "Chart.yaml", "values.yaml",
            "templates/deployment.yaml", "templates/service.yaml",
            "templates/ingress.yaml", "templates/pvc.yaml",
            "templates/_helpers.tpl",
        ],
        "airgap_includes": [
            "chart.tgz", "values.yaml", "install.sh",
            "image-manifest.txt", "README.md",
        ],
    }
