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
# Branch document (rule 11): architecture, design decisions, open issues. Committed with the branch, kept after it merges.
if [ "$repo" = portal ]; then doc="$dir/docs/branches/$topic.md"; else doc="$dir/docs/architecture/v4.0/branches/$topic.md"; fi
if [ ! -e "$doc" ]; then
  mkdir -p "$(dirname "$doc")"
  cat > "$doc" <<DOCEND
# $branch

Owner: <session / person> - Started: $(date +%Y-%m-%d) - Base: $base ($(git rev-parse --short "$base")) - Status: in progress

## Purpose
<one paragraph: what this branch delivers and why>

## Architecture
<what is built and where: components, files and paths, data flow, interfaces with other parts of v4>

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| <what was chosen> | <what was not> | <reason> |

## Open issues
- [ ] <unfinished, unverified or deferred item> (owner: <who>)

## Testing
<what was run, where (Nano on :8099 / headless Docker), and the result; what was NOT run>
DOCEND
fi
echo
echo "Created $dir on $branch from $base ($(git rev-parse --short "$base"))."
echo "Add this row to docs/architecture/v4.0/SESSION-CLAIMS.md (on the trunk) before editing shared paths:"
echo "| <session> | $branch | $repo | <paths you will edit> | $(date +%Y-%m-%d) |"
echo "Fill in the branch document (architecture, design decisions, open issues): ${doc#$dir/}"
echo "Push the topic branch at once: git push -u origin $branch"
