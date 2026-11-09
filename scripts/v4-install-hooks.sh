#!/bin/sh
# Opt this clone in to the committed git hooks (layer 6). Safe to re-run.
set -e
root=$(git rev-parse --show-toplevel)
git -C "$root" config core.hooksPath .githooks
echo "core.hooksPath = .githooks  (pre-push: topic branches never blocked; trunk/main/tags guarded)"
