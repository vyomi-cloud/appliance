#!/usr/bin/env bash
# Shallow-clone the Vyomi MCP eval corpus listed in corpus.tsv into ./corpus/.
# Monorepos use a sparse checkout of only the listed paths, so the whole set
# stays at a few GB. Re-running skips repos that are already cloned.
#
#   ./clone_corpus.sh            # everything
#   ./clone_corpus.sh A          # only tier A (the "do tests pass" set)
set -euo pipefail

TIER="${1:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HERE/corpus"

grep -v '^#' "$HERE/corpus.tsv" | while IFS=$'\t' read -r repo tier sparse why; do
  [ -z "$repo" ] && continue
  [ -n "$TIER" ] && [ "$tier" != "$TIER" ] && continue
  dest="$HERE/corpus/$(echo "$repo" | tr '/' '__')"
  if [ -d "$dest/.git" ]; then echo "= $repo (already cloned)"; continue; fi
  echo "+ $repo  [$tier]  $why"
  if [ -n "$sparse" ]; then
    git clone --quiet --depth 1 --filter=blob:none --sparse "https://github.com/$repo.git" "$dest"
    # shellcheck disable=SC2086
    git -C "$dest" sparse-checkout set $sparse
  else
    git clone --quiet --depth 1 --filter=blob:none "https://github.com/$repo.git" "$dest"
  fi || echo "! failed: $repo (renamed or moved? check on github.com)"
done

echo
du -sh "$HERE/corpus" 2>/dev/null || true
echo "Next: scan with max_files raised for the monorepos, e.g. \"max_files\":50000"
