#!/usr/bin/env bash
# Build a .deb package from the CloudLearn source tree using fpm.
#
# Usage:  bash packaging/debian/build-deb.sh [version]
#         version defaults to the contents of VERSION at repo root.
#
# Requires: fpm (gem install fpm), tar, gzip.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VERSION="${1:-$(tr -d '[:space:]' < VERSION)}"
if [ -z "$VERSION" ]; then
  echo "ERROR: no version (pass arg or set VERSION file)" >&2
  exit 1
fi

DIST="${DIST:-$ROOT/dist}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Layout (FHS-compliant):
#   /usr/lib/cloud-learn/         — bundled source + Dockerfile + compose
#   /usr/bin/cloud-learn           — launcher wrapper
#   /usr/share/doc/cloud-learn/    — README + LICENSE + CHANGELOG
#   /usr/share/man/man1/cloud-learn.1 — manpage (optional)
mkdir -p "$STAGE/usr/lib/cloud-learn"
mkdir -p "$STAGE/usr/bin"
mkdir -p "$STAGE/usr/share/doc/cloud-learn"

# Bundle the source the appliance VM syncs to /workspace/cloud-learn
cp -r core providers packs static scripts \
      server.py requirements.txt VERSION Dockerfile \
      docker-compose.yml docker-compose.appliance.yml .env.example \
      "$STAGE/usr/lib/cloud-learn/"

# Launcher wrapper
cat > "$STAGE/usr/bin/cloud-learn" <<'EOF'
#!/usr/bin/env bash
export CLOUD_LEARN_HOME="${CLOUD_LEARN_HOME:-/usr/lib/cloud-learn}"
export CLOUDLEARN_DISTRIBUTION_MODE="${CLOUDLEARN_DISTRIBUTION_MODE:-appliance}"
exec bash "$CLOUD_LEARN_HOME/scripts/cloud-learn" "$@"
EOF
chmod 0755 "$STAGE/usr/bin/cloud-learn"

# Docs
cp README.md LICENSE CHANGELOG.md "$STAGE/usr/share/doc/cloud-learn/" 2>/dev/null || true

mkdir -p "$DIST"

# Build the .deb
fpm \
  --input-type dir \
  --output-type deb \
  --name cloud-learn \
  --version "$VERSION" \
  --architecture all \
  --license MIT \
  --maintainer "CloudLearn <support@cloudlearn.io>" \
  --vendor "CloudLearn" \
  --description "Local multi-cloud simulator (AWS/GCP/Azure) with real backends" \
  --url "https://github.com/cloudlearn/cloud-learn" \
  --depends "bash" \
  --depends "curl" \
  --depends "ca-certificates" \
  --recommends "multipass" \
  --recommends "docker.io | docker-ce" \
  --deb-suggests "qemu-system-x86" \
  --deb-recommends "snapd" \
  --after-install "$ROOT/packaging/debian/postinst.sh" \
  --before-remove "$ROOT/packaging/debian/prerm.sh" \
  --chdir "$STAGE" \
  --package "$DIST/cloud-learn_${VERSION}_all.deb" \
  .

echo
echo "==> Built: $DIST/cloud-learn_${VERSION}_all.deb"
ls -la "$DIST/cloud-learn_${VERSION}_all.deb"
