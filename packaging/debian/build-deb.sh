#!/usr/bin/env bash
# Build a .deb package from the Vyomi source tree using fpm.
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
# /usr/share/vyomi/packaging/common/ houses the install-funnel phone-home
# script invoked from postinst.sh. Kept under /usr/share (not /usr/lib)
# because it's a tiny standalone shell script with no dependency on the
# bundled python tree.
mkdir -p "$STAGE/usr/share/vyomi/packaging/common"

# Bundle the source the appliance VM syncs to /workspace/cloud-learn
cp -r core providers packs static scripts \
      server.py requirements.txt VERSION Dockerfile \
      docker-compose.yml docker-compose.appliance.yml .env.example \
      "$STAGE/usr/lib/cloud-learn/"

# Phone-home script + VERSION (so it can self-report the right version
# without depending on /usr/lib/cloud-learn being readable).
cp packaging/common/phone-home.sh "$STAGE/usr/share/vyomi/packaging/common/phone-home.sh"
chmod 0755 "$STAGE/usr/share/vyomi/packaging/common/phone-home.sh"
cp VERSION "$STAGE/usr/share/vyomi/packaging/common/VERSION"

# Primary launcher: /usr/bin/vyomi
cat > "$STAGE/usr/bin/vyomi" <<'EOF'
#!/usr/bin/env bash
export CLOUD_LEARN_HOME="${CLOUD_LEARN_HOME:-/usr/lib/cloud-learn}"
export CLOUDLEARN_DISTRIBUTION_MODE="${CLOUDLEARN_DISTRIBUTION_MODE:-appliance}"
exec bash "$CLOUD_LEARN_HOME/scripts/cloud-learn" "$@"
EOF
chmod 0755 "$STAGE/usr/bin/vyomi"

# Legacy shim: /usr/bin/cloud-learn → /usr/bin/vyomi with deprecation warning
cat > "$STAGE/usr/bin/cloud-learn" <<'EOF'
#!/usr/bin/env bash
if [ -z "$VYOMI_NO_DEPRECATION_WARN" ] && [ -t 2 ]; then
  printf '\033[33mNote:\033[0m \033[2m`cloud-learn` is deprecated. Use `vyomi` instead. Suppress: VYOMI_NO_DEPRECATION_WARN=1\033[0m\n' >&2
fi
exec /usr/bin/vyomi "$@"
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
  --maintainer "Vyomi <support@vyomi.cloud>" \
  --vendor "Vyomi" \
  --description "Local multi-cloud simulator (AWS/GCP/Azure) with real backends" \
  --url "https://github.com/vyomi-cloud/appliance" \
  --depends "bash" \
  --depends "curl" \
  --depends "ca-certificates" \
  --deb-recommends "multipass" \
  --deb-recommends "docker.io | docker-ce" \
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
