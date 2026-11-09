#!/bin/sh
# Start a v4 topic the right way (docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md, layer 7).
#   scripts/v4-session-start.sh <topic> [--portal] [--dry-run]
# Creates ../appliance-<topic> (branch v4/<topic>) off a FRESH origin/v4-on-main, or ../portal-<topic> (branch portal/<topic>)
# off origin/v4-nano-portal with --portal, installs the hooks, and prints the claims row to add to SESSION-CLAIMS.md.
set -e
topic=""; portal=0; dry=0
for a in "$@"; do case "$a" in --portal) portal=1;; --dry-run) dry=1;; -*) echo "unknown flag $a"; exit 2;; *) topic=$a;; esac; done
[ -n "$topic" ] || { echo "usage: $0 <topic> [--portal] [--dry-run]"; exit 2; }
echo "$topic" | grep -Eq '^[A-Za-z0-9._-]+$' || { echo "topic must match [A-Za-z0-9._-]+"; exit 2; }
if [ "$portal" = 1 ]; then base=origin/v4-nano-portal; branch="portal/$topic"; dir="../portal-$topic"; repo=portal
else base=origin/v4-on-main; branch="v4/$topic"; dir="../appliance-$topic"; repo=appliance; fi
[ "$dry" = 1 ] && { echo "would: git fetch origin; git worktree add $dir -b $branch $base"; exit 0; }
git fetch -q origin
[ -e "$dir" ] && { echo "$dir already exists"; exit 1; }
git rev-parse --verify -q "$branch" >/dev/null 2>&1 && { echo "branch $branch already exists locally"; exit 1; }
git worktree add "$dir" -b "$branch" "$base"
( cd "$dir" && [ -x scripts/v4-install-hooks.sh ] && scripts/v4-install-hooks.sh || true )
echo
echo "Created $dir on $branch from $base ($(git rev-parse --short "$base"))."
echo "Add this row to docs/architecture/v4.0/SESSION-CLAIMS.md (on the trunk) before editing shared paths:"
echo "| <session> | $branch | $repo | <paths you will edit> | $(date +%Y-%m-%d) |"
echo "Push the topic branch at once: git push -u origin $branch"
