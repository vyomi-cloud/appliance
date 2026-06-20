#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
export LANG=C

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="${CLOUD_LEARN_VERSION_FILE:-${ROOT_DIR}/VERSION}"
DIST_DIR="${CLOUD_LEARN_DIST_DIR:-${ROOT_DIR}/dist}"
RELEASE_NAME="${CLOUD_LEARN_RELEASE_NAME:-cloud-learn}"

if [ ! -f "$VERSION_FILE" ]; then
  printf 'Version file not found: %s\n' "$VERSION_FILE" >&2
  exit 1
fi

VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
if [ -z "$VERSION" ]; then
  printf 'Version file is empty: %s\n' "$VERSION_FILE" >&2
  exit 1
fi

mkdir -p "$DIST_DIR"

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/cloud-learn-release.XXXXXX")"
cleanup() {
  rm -rf "$STAGE_DIR"
}
trap cleanup EXIT

RELEASE_DIR="${STAGE_DIR}/${RELEASE_NAME}-${VERSION}"
mkdir -p "$RELEASE_DIR"

copy_item() {
  local item="$1"
  if [ -e "${ROOT_DIR}/${item}" ]; then
    cp -R "${ROOT_DIR}/${item}" "${RELEASE_DIR}/"
  fi
}

copy_item "Dockerfile"
copy_item "VERSION"
copy_item "core"
copy_item "cloudsim-backbone"
copy_item "docker-compose.appliance.yml"
copy_item "requirements.txt"
copy_item "scripts"
copy_item "server.py"
copy_item "docs"
copy_item "static"
copy_item "tools"
copy_item "packaging"
# Aligned with packaging/debian/build-deb.sh + packaging/rpm/cloud-learn.spec
# (which already bundle these). The tarball previously omitted routes/providers/
# packs/setup_cython.py/docker-compose.yml/.env.example — fine when the simulator
# image is pulled, but the build-from-source fallback (Dockerfile COPY routes …)
# and the launcher's source-sync need the complete set.
copy_item "routes"
copy_item "providers"
copy_item "packs"
copy_item "setup_cython.py"
copy_item "docker-compose.yml"
copy_item ".env.example"

TARBALL="${DIST_DIR}/${RELEASE_NAME}-${VERSION}.tar.gz"
tar -C "$STAGE_DIR" -czf "$TARBALL" "${RELEASE_NAME}-${VERSION}"

if command -v shasum >/dev/null 2>&1; then
  SHA256="$(shasum -a 256 "$TARBALL" | awk '{print $1}')"
elif command -v openssl >/dev/null 2>&1; then
  SHA256="$(openssl dgst -sha256 "$TARBALL" | awk '{print $2}')"
else
  printf 'Neither shasum nor openssl is available to compute sha256.\n' >&2
  exit 1
fi

printf 'Release tarball: %s\n' "$TARBALL"
printf 'SHA256: %s\n' "$SHA256"

cat <<EOF
Use the following values in the Homebrew formula:
  url "https://example.com/releases/${RELEASE_NAME}-${VERSION}.tar.gz"
  sha256 "${SHA256}"
EOF
