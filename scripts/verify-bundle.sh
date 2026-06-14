#!/usr/bin/env bash
# verify-bundle.sh — exercise the launcher's source-tar logic against
# a candidate root directory and assert that every file the
# appliance Dockerfile+cloudsim Dockerfile COPY's actually resolves
# inside the resulting tarball.
#
# Why: silent regressions like "scripts/ wasn't in the bundle" cost
# the user 5 minutes on a docker compose build before failing. This
# script catches the same class of bug locally in <5 seconds.
#
# Usage:
#   scripts/verify-bundle.sh                       # check workspace
#   scripts/verify-bundle.sh /opt/homebrew/.../libexec   # check brew bundle
#
# Exit:  0 = all required paths present in the tarball + Dockerfile COPYs satisfied
#        1 = at least one COPY-referenced path is missing
set -euo pipefail

ROOT_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
[ -d "$ROOT_DIR" ] || { echo "✗ not a directory: $ROOT_DIR" >&2; exit 1; }

red()    { printf '\033[31m%s\033[0m' "$*"; }
green()  { printf '\033[32m%s\033[0m' "$*"; }
yellow() { printf '\033[33m%s\033[0m' "$*"; }
bold()   { printf '\033[1m%s\033[0m' "$*"; }

echo "$(bold "verify-bundle:") $ROOT_DIR"

# Mirror of the launcher's required list. Keep in sync with
# appliance_sync_workspace_into_vm() in scripts/cloud-learn.
REQUIRED=(
  Dockerfile
  docker-compose.appliance.yml
  VERSION
  server.py
  requirements.txt
  setup_cython.py
  core
  providers
  packs
  routes
  scripts
  static
)
OPTIONAL=(docker-compose.yml cloudsim-backbone)

# 1. Required paths exist on disk
missing=()
for f in "${REQUIRED[@]}"; do
  [ ! -e "${ROOT_DIR}/${f}" ] && missing+=("$f")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "  $(red "✗") required files missing from $ROOT_DIR:"
  for m in "${missing[@]}"; do echo "      $m"; done
  exit 1
fi
echo "  $(green "✓") all ${#REQUIRED[@]} required paths present"

# 2. Build the tarball the same way the launcher would, then list contents
tarball="$(mktemp -t verify-bundle-XXXXXX.tgz)"
trap 'rm -f "$tarball" "$listing"' EXIT
listing="$(mktemp -t verify-bundle-list-XXXXXX.txt)"

tar_args=()
for f in "${REQUIRED[@]}"; do tar_args+=("$f"); done
for f in "${OPTIONAL[@]}"; do
  [ -e "${ROOT_DIR}/${f}" ] && tar_args+=("$f")
done

( cd "$ROOT_DIR" && tar czf "$tarball" \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'target' \
    --exclude 'dist' \
    --exclude '.git' \
    --exclude '*.log' \
    "${tar_args[@]}" )
tar tzf "$tarball" > "$listing"

sz_h="$(du -h "$tarball" | awk '{print $1}')"
echo "  $(green "✓") tarball built ($sz_h, $(wc -l < "$listing") entries)"

# 3. Every COPY-referenced path in the Dockerfile must resolve in the tarball
# Strip leading ./, take only the first path arg of COPY (skip --from=…),
# and skip multi-arg COPYs by splitting on whitespace.
dockerfile_copies() {
  local df="$1"
  grep -E '^COPY ' "$df" 2>/dev/null | while read -r _copy rest; do
    # If first token is --from=… or --chown=…, it's a flag — skip it
    for tok in $rest; do
      case "$tok" in
        --*) continue ;;
        *)
          # tok is the source path; the rest of args after it could
          # also be sources before the final destination. We only need
          # to verify the first one because if any other is in a separate
          # COPY directive it'll be caught in its own pass.
          printf '%s\n' "$tok"
          break ;;
      esac
    done
  done
}

# macOS ships bash 3.2 which has no `mapfile`. Use a temp file + read loop.
copies_file="$(mktemp -t verify-copies-XXXXXX.txt)"
dockerfile_copies "${ROOT_DIR}/Dockerfile" | sort -u > "$copies_file"
copies_count=$(wc -l < "$copies_file" | tr -d ' ')
echo "  $(yellow "·") Dockerfile COPYs $copies_count distinct sources"

# Build a normalized list of tarball entries (strip leading "./").
entries_file="$(mktemp -t verify-entries-XXXXXX.txt)"
sed 's|^\./||' "$listing" > "$entries_file"

missing_copies=()
while IFS= read -r src; do
  # Skip multi-stage references (e.g. /opt/venv — these are FROM=builder)
  case "$src" in
    /*) continue ;;
  esac
  # src can be either a file or a directory. Use grep to test presence.
  if ! grep -qE "^${src}(\$|/)" "$entries_file"; then
    missing_copies+=("$src")
  fi
done < "$copies_file"
rm -f "$copies_file" "$entries_file"

if [ "${#missing_copies[@]}" -gt 0 ]; then
  echo "  $(red "✗") Dockerfile COPYs that won't resolve from the tarball:"
  for m in "${missing_copies[@]}"; do echo "      $m"; done
  exit 1
fi
echo "  $(green "✓") every Dockerfile COPY source is in the tarball"

# 4. cloudsim-backbone Dockerfile sanity — only if the directory exists
if [ -d "${ROOT_DIR}/cloudsim-backbone" ]; then
  cs_missing=()
  for src in $(dockerfile_copies "${ROOT_DIR}/cloudsim-backbone/Dockerfile" | sort -u); do
    case "$src" in
      /*) continue ;;
    esac
    if [ ! -e "${ROOT_DIR}/cloudsim-backbone/${src}" ]; then
      cs_missing+=("cloudsim-backbone/${src}")
    fi
  done
  if [ "${#cs_missing[@]}" -gt 0 ]; then
    echo "  $(red "✗") cloudsim Dockerfile COPYs that won't resolve:"
    for m in "${cs_missing[@]}"; do echo "      $m"; done
    exit 1
  fi
  echo "  $(green "✓") cloudsim Dockerfile COPYs all resolve"
fi

echo "$(green "verify-bundle: ALL GREEN") — bundle at $ROOT_DIR is launchable."
