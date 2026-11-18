#!/usr/bin/env bash
# Build the vyomi-mcp binaries that the vyomi-tunnel npm package bundles (packaging option C): `vyomi-tunnel mcp` runs
# mcp/<platform>-<arch>/vyomi-mcp[.exe] (wasm/relay/mcp-launch.mjs). Node's platform/arch names, five targets.
#
#   scripts/build_tunnel_mcp.sh [outdir]        default outdir: packaging/tunnel/mcp (git-ignored: never commit the binaries)
#
# Needs go (cmd/vyomi/go.mod), python3 and node: gen_mcp_matrix.py first refreshes the embedded knowledge (VERSION, capabilities,
# docs snippets rendered by wasm/nano-docs.js). Run by .github/workflows/tunnel-release.yml right before npm pack / npm publish.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
out=${1:-$root/packaging/tunnel/mcp}
case "$out" in /*) ;; *) out="$PWD/$out" ;; esac
cd "$root"

python3 scripts/gen_mcp_matrix.py

for t in darwin/arm64:darwin-arm64 darwin/amd64:darwin-x64 linux/arm64:linux-arm64 linux/amd64:linux-x64 windows/amd64:win32-x64; do
  goos=${t%%/*}; rest=${t#*/}; goarch=${rest%%:*}; node_name=${t#*:}
  ext=""; [ "$goos" = windows ] && ext=".exe"
  dir="$out/$node_name"; bin="$dir/vyomi-mcp$ext"
  mkdir -p "$dir"; rm -f "$bin"
  GOOS="$goos" GOARCH="$goarch" CGO_ENABLED=0 go -C cmd/vyomi build -trimpath -ldflags "-s -w" -o "$bin" .
  chmod 755 "$bin"
  printf '%-14s %s\n' "$node_name" "$(du -h "$bin" | cut -f1)"
done
