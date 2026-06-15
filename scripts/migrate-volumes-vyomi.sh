#!/usr/bin/env bash
# migrate-volumes-vyomi.sh — Phase 11 of the v2.0.0 vyomi rebrand.
#
# One-time migration: copy the contents of every legacy `cloudlearn-*`
# Docker named volume into the new `vyomi-*` equivalent. Safe to run
# multiple times — only copies when the new volume is empty AND the
# old volume has content.
#
# Why this is a separate script (not auto-run via compose init container):
#   1. compose init containers run on every `up`, adding 1-2s overhead
#      for every release after v2.0.0. Not worth it for a one-time event.
#   2. Compose v2 doesn't have a clean "run once, ever" primitive.
#   3. Users upgrading from v1.x → v2.0.0 expect a documented migration
#      step. Auto-magic data movement during `up` is harder to trust.
#
# Usage:
#   1. docker compose down                  (stop the stack but keep volumes)
#   2. bash scripts/migrate-volumes-vyomi.sh
#   3. docker compose up -d                 (will now use vyomi-* volumes)
#
# Verify after step 2:
#   docker volume ls | grep -E 'vyomi-|cloudlearn-'
#   # The legacy cloudlearn-* volumes are LEFT IN PLACE (untouched). Once
#   # you've verified the vyomi-* volumes work, delete the legacy ones:
#   #   docker volume rm cloudlearn-data cloudlearn-sql-pg ...
#
# Idempotent: re-running is a no-op once vyomi-* volumes have content.
set -euo pipefail

# 9 volume mappings (legacy → canonical). Keep in sync with the
# volumes: blocks in docker-compose.yml + docker-compose.appliance.yml.
MAPPINGS=(
  "cloudlearn-data:vyomi-data"
  "cloudlearn-sql-pg:vyomi-sql-pg"
  "cloudlearn-sql-mysql:vyomi-sql-mysql"
  "cloudlearn-gcs:vyomi-gcs"
  "cloudlearn-nats:vyomi-nats"
  "cloudlearn-minio:vyomi-minio"
  "cloudlearn-dynamodb:vyomi-dynamodb"
  "cloudlearn-portal-keys:vyomi-portal-keys"
  "cloudlearn-portal-data:vyomi-portal-data"
)

BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; RESET=$'\033[0m'

echo "${BOLD}Vyomi volume migration${RESET}  —  cloudlearn-* → vyomi-*"
echo ""

if ! command -v docker >/dev/null 2>&1; then
  echo "${YELLOW}✗ docker not on PATH${RESET}" >&2
  exit 1
fi

# Sanity: warn if the stack is currently running. Stopped is safer for the copy.
if docker compose ps --status running 2>/dev/null | grep -qE 'simulator|cloudsim'; then
  echo "${YELLOW}⚠ Compose stack appears to be running.${RESET}"
  echo "  Run 'docker compose down' first to ensure a clean copy."
  echo "  Continuing anyway in 5 seconds (Ctrl-C to abort)..."
  sleep 5
fi

migrated=0
skipped=0
for pair in "${MAPPINGS[@]}"; do
  old="${pair%%:*}"
  new="${pair##*:}"

  # Does the legacy volume exist?
  if ! docker volume inspect "$old" >/dev/null 2>&1; then
    echo "  ${DIM}·${RESET} ${old} (no legacy volume — skipping)"
    skipped=$((skipped + 1))
    continue
  fi

  # Create new volume if absent. Idempotent.
  docker volume create "$new" >/dev/null

  # Is the new volume already populated? If so, leave it alone.
  has_content=$(docker run --rm -v "${new}:/v" alpine sh -c 'ls -A /v 2>/dev/null | head -1')
  if [ -n "$has_content" ]; then
    echo "  ${DIM}·${RESET} ${new} (already has content — skipping)"
    skipped=$((skipped + 1))
    continue
  fi

  # Copy old → new. Use alpine for size; -av preserves symlinks/permissions.
  echo "  ${GREEN}→${RESET} ${old} → ${new}"
  docker run --rm \
    -v "${old}:/from:ro" \
    -v "${new}:/to" \
    alpine sh -c "cp -av /from/. /to/ >/dev/null 2>&1"
  migrated=$((migrated + 1))
done

echo ""
echo "${BOLD}Summary${RESET}: ${migrated} migrated, ${skipped} skipped (already done or no legacy)"
echo ""
echo "${BOLD}Next steps${RESET}:"
echo "  1. ${GREEN}docker compose up -d${RESET}    — the stack now uses the vyomi-* volumes"
echo "  2. Verify your data is intact (login, browse, etc.)"
echo "  3. Once happy, delete the legacy volumes to reclaim disk:"
echo "     ${DIM}docker volume rm ${MAPPINGS[*]%%:*}${RESET}"
echo ""
echo "${YELLOW}NOTE${RESET}: legacy cloudlearn-* volumes are LEFT IN PLACE in case you"
echo "      need to roll back. They're not garbage-collected automatically."
