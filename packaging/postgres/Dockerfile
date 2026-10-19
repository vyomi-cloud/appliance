# vyomi/postgres:16-alpine-pgvector
# Multi-arch (linux/amd64, linux/arm64) PostgreSQL 16 image with pgvector compiled in.
# Uses the same Alpine base as postgres:16-alpine to ensure full binary & collation compatibility
# without requiring data directory migration.
# Pinned official multi-arch digest for postgres:16-alpine (16.15-alpine3.24)
FROM postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea

LABEL org.opencontainers.image.title="Vyomi PostgreSQL with pgvector" \
      org.opencontainers.image.description="PostgreSQL 16 Alpine with pgvector extension compiled from source" \
      org.opencontainers.image.vendor="Vyomi Cloud"

ARG PGVECTOR_VERSION=v0.8.0

RUN set -eux; \
    apk add --no-cache --virtual .build-deps \
        git \
        build-base \
    ; \
    git clone --depth 1 --branch "$PGVECTOR_VERSION" https://github.com/pgvector/pgvector.git /tmp/pgvector; \
    cd /tmp/pgvector; \
    make OPTFLAGS="" with_llvm=no; \
    make install with_llvm=no; \
    cd /; \
    rm -rf /tmp/pgvector; \
    apk del --no-network .build-deps
