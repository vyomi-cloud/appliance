#!/usr/bin/env bash
# Publish one course folder as its own standalone repository, so "Open in editor" / Codespaces opens ONLY that course, never the appliance.
# Source of truth stays in the appliance (courses/<slug>/); the standalone repo is a mirror of that folder. Pushing needs the owner's go.
# usage: scripts/sync_course_repo.sh vyomi-labs-facilities-agent [--push]
set -euo pipefail
slug="${1:?course slug}"; org="vyomi-cloud"
cd "$(git rev-parse --show-toplevel)"
"${PYTHON:-python3}" -m vyomilabs.content.build_project >/dev/null          # regenerate so the mirror matches the course data
sha=$(git subtree split --prefix="courses/$slug")
echo "course tree $sha for $org/$slug"
if [ "${2:-}" = "--push" ]; then
  # first publish of a course creates its repository, so every future course gets a valid, standalone repo automatically
  if ! gh repo view "$org/$slug" >/dev/null 2>&1; then
    desc=$(head -3 "courses/$slug/README.md" | tail -1 | cut -c1-200)
    gh repo create "$org/$slug" --public --description "${desc:-Vyomi Labs course project}"
  fi
  git push --force "https://github.com/$org/$slug.git" "$sha:refs/heads/main"   # mirror: the appliance copy is the source of truth
else echo "dry run: add --push to publish"; fi
