# Multi-stage Dockerfile for cloudlearn/simulator.
#   stage 1 (builder): install Python deps into /opt/venv  → cacheable
#   stage 2 (runtime): copy /opt/venv + app, no build tools in final image
#
# Final image: python:3.14-slim base + virtualenv + Node.js runtime
# (for Cloud Functions exec), ~150 MB compressed.
#
# Build:   docker build -t cloudlearn/simulator:1.0.0 .
# Run:     docker run --rm -p 9000:9000 cloudlearn/simulator:1.0.0

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
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the populated venv from builder
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# App source — copied AFTER venv so dependency-only changes don't bust the cache
COPY core   /app/core
COPY providers /app/providers
COPY packs  /app/packs
COPY static /app/static
COPY server.py requirements.txt VERSION /app/

# OCI image labels — surface in docker inspect + GH container registry UI
LABEL org.opencontainers.image.title="CloudLearn Simulator" \
      org.opencontainers.image.description="Local multi-cloud simulator (AWS/GCP/Azure) with real backends" \
      org.opencontainers.image.url="https://github.com/cloudlearn/cloud-learn" \
      org.opencontainers.image.source="https://github.com/cloudlearn/cloud-learn" \
      org.opencontainers.image.documentation="https://github.com/cloudlearn/cloud-learn/blob/main/README.md" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="1.0.0"

VOLUME ["/data"]
EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:9000/healthz || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000"]
