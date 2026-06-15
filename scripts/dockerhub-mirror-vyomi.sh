#!/usr/bin/env bash
# dockerhub-mirror-vyomi.sh — Phase 3 of the v2.0.0 vyomi rebrand.
#
# Re-publishes every existing gansudkum/cloud-learn:X.Y.Z multi-arch tag
# as vyomi/appliance:X.Y.Z on Docker Hub, plus the :latest pointer.
#
# Why a script (not just buildx push --tag): the existing images are
# already built + signed by the release pipeline. Rebuilding from source
# would change the digest, breaking anyone who pinned a specific digest.
# `docker buildx imagetools create` copies the manifest verbatim — same
# digest, same content, just a new tag.
#
# Prereqs (do these BEFORE running the script):
#   1. `docker login` as the `vyomi` Docker Hub account (NOT gansudkum)
#   2. Create the empty vyomi/appliance repository in the Hub UI
#   3. Buildx is available (Docker Desktop has it by default)
#
# Usage:
#   bash scripts/dockerhub-mirror-vyomi.sh
#   bash scripts/dockerhub-mirror-vyomi.sh --dry-run   # show what would push
#
# Idempotent: re-running just re-copies the same manifests (no-op cost).
set -euo pipefail

SRC_REPO="gansudkum/cloud-learn"
DST_REPO="vyomi/appliance"

# Tags to mirror — everything currently published.
# Add new tags here as future releases come out, OR delete this script
# once release.yml is updated to publish directly to vyomi/appliance.
TAGS=(
  "1.2.1"
  "1.2.2"
  "1.2.3"
  "1.2.4"
  "1.2.5"
  "latest"
)

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
fi

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'

echo "${BOLD}Docker Hub mirror — ${SRC_REPO} → ${DST_REPO}${RESET}"
echo "Tags to mirror: ${TAGS[*]}"
echo ""

# Sanity: confirm logged in as `vyomi` (not gansudkum). The auth file in
# ~/.docker/config.json has the active credential.
if ! command -v docker >/dev/null 2>&1; then
  echo "${RED}docker not on PATH — install Docker Desktop first${RESET}" >&2
  exit 1
fi

# We use `crane` rather than `docker buildx imagetools create` because
# imagetools fails with HTTP 400 on cross-namespace multi-arch copies
# when the source and destination are different Docker Hub accounts
# (verified: gansudkum → vyomi fails at the blob upload stage).
# Crane uses the registry's native blob-mount + pull-then-push fallback
# and works reliably for cross-namespace copies. Reads auth from the
# same ~/.docker/config.json so `docker login -u vyomi` is reused.
if ! command -v crane >/dev/null 2>&1; then
  echo "${RED}✗ crane not on PATH${RESET}" >&2
  echo "  Install with:  brew install crane" >&2
  echo "  Or download:   https://github.com/google/go-containerregistry/releases" >&2
  exit 1
fi
echo "${YELLOW}==> Crane found:${RESET} $(crane version 2>&1 | head -1)"
echo "${YELLOW}==> Docker Hub auth: ~/.docker/config.json (reused from \`docker login -u vyomi\`)${RESET}"
echo ""
echo "If you're not logged in as 'vyomi' yet, stop and run:"
echo "   docker logout && docker login -u vyomi"
echo ""
read -r -p "Continue? [y/N] " ans
case "${ans:-n}" in
  y|Y|yes|YES) ;;
  *) echo "Aborted."; exit 0 ;;
esac

ok=0
failed=()
for tag in "${TAGS[@]}"; do
  src="${SRC_REPO}:${tag}"
  dst="${DST_REPO}:${tag}"
  echo "${BOLD}==> ${src} → ${dst}${RESET}"
  if [ "$DRY_RUN" = "1" ]; then
    echo "    (dry-run)  crane copy ${src} ${dst}"
    ok=$((ok + 1))
    continue
  fi
  if crane copy "$src" "$dst" 2>&1 | sed 's/^/    /'; then
    echo "    ${GREEN}✓ ${dst} published${RESET}"
    ok=$((ok + 1))
  else
    echo "    ${RED}✗ ${dst} failed${RESET}"
    failed+=("$tag")
  fi
done

echo ""
echo "${BOLD}Summary${RESET}: ${ok}/${#TAGS[@]} tags mirrored"
if [ "${#failed[@]}" -gt 0 ]; then
  echo "  ${RED}Failed:${RESET} ${failed[*]}"
  exit 1
fi

echo ""
echo "${GREEN}All tags mirrored. Verify with:${RESET}"
echo "   curl -fsS 'https://hub.docker.com/v2/repositories/${DST_REPO}/tags/?page_size=10' | jq '.results[].name'"
echo "   docker pull ${DST_REPO}:latest"
echo "   docker run --rm ${DST_REPO}:latest python -c 'import server; print(\"ok\")'"
