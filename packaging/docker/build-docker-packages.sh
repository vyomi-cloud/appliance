#!/usr/bin/env bash
# Build the vyomi-docker .deb + .rpm — a thin Docker-substrate launcher for the
# Free / Lite / Pro tiers. Ships ONLY the `vyomi` wrapper + the pull-only
# docker-compose.cloudlite.yml (no Multipass, no LXD, no simulator source).
#
# Contrast with the `cloud-learn` package (the Multipass/Max launcher), which
# bundles the full source + boots a Multipass VM. The two CONFLICT (both own
# /usr/bin/vyomi) — a host installs one or the other.
#
# Requires: fpm on PATH. Run from anywhere; paths are resolved from the repo.
#   bash packaging/docker/build-docker-packages.sh <version>
set -euo pipefail

VERSION="${1:?usage: build-docker-packages.sh <version>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

STAGE="$(mktemp -d)"
mkdir -p "$STAGE/usr/bin" "$STAGE/usr/share/vyomi-docker" "$STAGE/usr/share/doc/vyomi-docker"

install -m 0755 "$ROOT/packaging/docker/vyomi"              "$STAGE/usr/bin/vyomi"
install -m 0644 "$ROOT/docker-compose.cloudlite.yml"        "$STAGE/usr/share/vyomi-docker/docker-compose.cloudlite.yml"
install -m 0644 "$ROOT/README.md" "$ROOT/LICENSE"           "$STAGE/usr/share/doc/vyomi-docker/"

mkdir -p "$ROOT/dist"

# Common fpm args. Docker isn't hard-depended (users install it via Docker
# Desktop / docker-ce repo / distro, under different package names) — the
# wrapper checks for it at runtime; deb adds a soft Recommends.
common=(
  -s dir -n vyomi-docker -v "$VERSION"
  --license BUSL-1.1 --architecture noarch
  --maintainer "Vyomi <support@vyomi.cloud>"
  --url "https://github.com/vyomi-cloud/appliance"
  --description "Vyomi (Docker substrate) — Free/Lite/Pro tiers. 'vyomi up' = docker compose up; no Multipass/LXD."
  --depends bash
  --conflicts cloud-learn
  --chdir "$STAGE"
)

fpm "${common[@]}" -t deb --deb-recommends docker.io \
    --package "$ROOT/dist/vyomi-docker_${VERSION}_all.deb" .
fpm "${common[@]}" -t rpm \
    --package "$ROOT/dist/vyomi-docker-${VERSION}-1.noarch.rpm" .

echo "==> Built:"
ls -1 "$ROOT"/dist/vyomi-docker-* "$ROOT"/dist/vyomi-docker_* 2>/dev/null || true
