# Multi-stage Dockerfile for vyomi/appliance.
#   stage 1 (builder): install Python deps into /opt/venv  → cacheable
#   stage 2 (runtime): copy /opt/venv + app, no build tools in final image
#
# Final image: python:3.14-slim base + virtualenv + Node.js runtime
# (for Cloud Functions exec), ~150 MB compressed.
#
# Build:   docker build -t vyomi/appliance:2.0.6 .
# Run:     docker run --rm -p 9000:9000 vyomi/appliance:2.0.6
#
# Published to Docker Hub: https://hub.docker.com/r/vyomi/appliance
#       and to GHCR:       https://ghcr.io/vyomi-cloud/appliance

# ───── builder ────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Build deps only in the builder; final image stays slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create venv + install requirements
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt /build/requirements.txt
RUN pip install -r requirements.txt

# ───── runtime ────────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    CLOUDLEARN_STATE_FILE=/data/cloudlearn_state.pkl \
    CLOUDLEARN_VERSION="1.0.0"

# Node.js for real Cloud Functions exec + curl for health-check container probes
# openssh-client = `ssh-keygen`, used by the Docker compute backend to mint the
# per-deploy instance keypair injected into launched instances (Pro tier SSH).
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs curl openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI (client only) — the CloudLite+ Docker compute backend
# (core/compute/backend.py) shells out to `docker` against the bind-mounted host
# socket (/var/run/docker.sock) to launch sibling instance containers. Static
# client binary, no daemon; multi-arch aware via TARGETARCH.
ARG DOCKER_CLI_VERSION=27.3.1
ARG TARGETARCH
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) DARCH=x86_64 ;; \
      arm64) DARCH=aarch64 ;; \
      *)     DARCH=x86_64 ;; \
    esac; \
    curl -fsSL "https://download.docker.com/linux/static/stable/${DARCH}/docker-${DOCKER_CLI_VERSION}.tgz" \
      | tar -xz -C /usr/local/bin --strip-components=1 docker/docker; \
    docker --version

# Copy the populated venv from builder
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

RUN addgroup --system cloudlearn && \
    adduser --system --ingroup cloudlearn cloudlearn && \
    mkdir -p /data /var/lib/cloudlearn/deployments && \
    chown -R cloudlearn:cloudlearn /app /data /var/lib/cloudlearn

# App source — copied AFTER venv so dependency-only changes don't bust the cache
COPY core   /app/core
COPY providers /app/providers
COPY packs  /app/packs
COPY routes /app/routes
COPY static /app/static
COPY scripts /app/scripts
COPY server.py requirements.txt VERSION /app/
COPY setup_cython.py /app/setup_cython.py

# ── Code protection (Layer 3): multi-layer obfuscation + compilation ─────
# STRIP_SOURCE=true  → full appliance hardening (obfuscate + Cython + .pyc + strip)
# STRIP_SOURCE=false → dev mode (plain source, no protection)
ARG STRIP_SOURCE=false
RUN if [ "$STRIP_SOURCE" = "true" ]; then \
    echo "=== Layer 3a: Obfuscating Python source ===" && \
    python /app/scripts/obfuscate_build.py /app && \
    echo "=== Layer 3b: Cython-compiling critical modules ===" && \
    pip install cython && \
    cd /app && python setup_cython.py build_ext --inplace && \
    rm -f core/state_integrity.py core/tier_policy.py core/license_remote.py && \
    echo "=== Layer 3c: Compiling all Python to bytecode ===" && \
    python -m compileall -b -q /app/core /app/providers /app/routes /app/packs /app && \
    echo "=== Layer 3d: Stripping all .py source files ===" && \
    find /app -name '*.py' ! -name '__init__.py' -delete && \
    rm -rf /app/scripts && \
    echo "=== Layer 3e: Generating integrity manifest ===" && \
    python -c "from core.integrity_check import generate_manifest, save_manifest; m=generate_manifest('/app'); save_manifest(m); print(f'Manifest: {m[\"file_count\"]} files')" && \
    echo "=== Code protection complete ==="; \
    fi

# OCI image labels — surface in `docker inspect`, the Docker Hub UI,
# the GitHub Container Registry UI, and any image scanner. The values
# below appear verbatim under "Image labels" on the Hub repo's
# Overview page and in the right-side metadata column.
#
# Image-version + revision + created come dynamically from
# docker-publish.yml's `labels:` block at push time; everything else
# is static and brand-aligned with vyomi.cloud.
LABEL org.opencontainers.image.title="Vyomi Appliance" \
      org.opencontainers.image.description="Local multi-cloud simulator (AWS/GCP/Azure) with real backends — full SDK + CLI parity for boto3, aws-sdk-java, google-cloud-*, azure-sdk-for-*, Terraform" \
      org.opencontainers.image.vendor="Vyomi" \
      org.opencontainers.image.authors="Vyomi <support@vyomi.cloud>" \
      org.opencontainers.image.url="https://vyomi.cloud" \
      org.opencontainers.image.source="https://github.com/vyomi-cloud/appliance" \
      org.opencontainers.image.documentation="https://vyomi.cloud/docs" \
      org.opencontainers.image.licenses="BUSL-1.1"

VOLUME ["/data"]
EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:9000/healthz || exit 1

USER cloudlearn

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000"]
