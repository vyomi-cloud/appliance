#!/usr/bin/env bash
# Publish the Codespaces sandbox template from this repo to the public template
# repo (vyomi-cloud/sandbox), the same author-here-sync-there pattern the Nano
# bundle uses. Run from the appliance repo root.
#
#   codespace/publish.sh /path/to/vyomi-cloud-sandbox-checkout
#
# Copies .devcontainer/ + README.md so a user opening the template repo in a
# Codespace gets the aws-core sandbox. Does NOT commit/push — review + commit
# in the template repo yourself.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:?usage: publish.sh <template-repo-checkout>}"

[ -d "$DEST" ] || { echo "destination not found: $DEST" >&2; exit 1; }

mkdir -p "$DEST/.devcontainer/profiles"
cp -v "$SRC/.devcontainer/devcontainer.json"          "$DEST/.devcontainer/"
cp -v "$SRC/.devcontainer/docker-compose.sandbox.yml" "$DEST/.devcontainer/"
cp -v "$SRC/.devcontainer/boot.sh"                     "$DEST/.devcontainer/"
cp -v "$SRC/.devcontainer/profiles/"*.json            "$DEST/.devcontainer/profiles/"
# Per-profile devcontainers (aws/gcp/azure) — the dedicated launch selects one of
# these (e.g. aws-core → .devcontainer/aws/devcontainer.json), so they MUST ship too.
for prof in aws gcp azure; do
  if [ -d "$SRC/.devcontainer/$prof" ]; then
    mkdir -p "$DEST/.devcontainer/$prof"
    cp -v "$SRC/.devcontainer/$prof/devcontainer.json" "$DEST/.devcontainer/$prof/"
  fi
done
cp -v "$SRC/README.md"                                 "$DEST/"
chmod +x "$DEST/.devcontainer/boot.sh"

echo "Published to $DEST — review + commit + push there."
