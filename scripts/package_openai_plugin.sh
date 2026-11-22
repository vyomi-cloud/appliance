#!/usr/bin/env bash
# Build the ZIP that is submitted to the OpenAI (ChatGPT / Codex) plugin directory:
#
#   bash scripts/package_openai_plugin.sh                 # -> dist/vyomi-cloud-openai.zip
#   bash scripts/package_openai_plugin.sh vyomi-cloud     # the plugin folder to package (default)
#
# OPENAI-DIRECTORY-PLAN.md WP-O3: "one plugin root, no siblings, no hooks". The archive therefore has exactly one
# top-level directory — the plugin folder — and nothing else: no marketplace files, no other plugin, no hooks, no
# git metadata, no macOS resource forks. The manifest checks run first, so a package can never be built from a
# folder the repo would reject.
#
# Only `plugins/vyomi-cloud` is submitted to OpenAI (HOSTED-MCP-DESIGN.md §7): it reaches the hosted server over
# HTTPS and needs nothing installed, which is what that directory accepts. The local `plugins/vyomi` stays
# installable from the marketplace.
set -euo pipefail
cd "$(dirname "$0")/.."

PLUGIN="${1:-vyomi-cloud}"
SRC="integrations/claude-plugins/plugins/${PLUGIN}"
OUT="dist/${PLUGIN}-openai.zip"

[ -d "$SRC" ] || { echo "package_openai_plugin: no such plugin folder: $SRC" >&2; exit 1; }
command -v zip >/dev/null || { echo "package_openai_plugin: needs the zip command" >&2; exit 1; }

echo "== manifest checks =="
python3 scripts/check_agent_plugins.py integrations/claude-plugins

# The submission is the remote plugin: refuse to package a folder that would make the user install anything.
python3 - "$SRC" <<'PY'
import json, pathlib, sys
src = pathlib.Path(sys.argv[1])
servers = json.loads((src / ".mcp.json").read_text())["mcpServers"]
for name, s in servers.items():
    if s.get("command") or s.get("type") not in ("http", "streamable-http", "sse"):
        sys.exit(f"package_openai_plugin: {src}/.mcp.json server {name} is not a remote server: {s}. "
                 "OpenAI limits local MCP submissions to approved partners (HOSTED-MCP-DESIGN.md §1).")
    if not (s.get("url") or "").startswith("https://"):
        sys.exit(f"package_openai_plugin: {src}/.mcp.json server {name} url must be https, got {s.get('url')!r}")
print(f"remote server only: {', '.join(f'{n} -> {s[chr(117)+chr(114)+chr(108)]}' for n, s in servers.items())}")
PY

echo
echo "== building $OUT =="
rm -rf dist/_openai "$OUT"
mkdir -p dist/_openai
# One plugin root, nothing beside it.
cp -R "$SRC" "dist/_openai/${PLUGIN}"
# No hooks, no git metadata, no editor or OS leftovers.
find "dist/_openai/${PLUGIN}" \
  \( -name '.git' -o -name '.github' -o -name 'hooks' -o -name 'node_modules' -o -name '__pycache__' \
     -o -name '.DS_Store' -o -name '._*' -o -name '*.pyc' \) -prune -exec rm -rf {} +

mkdir -p dist
( cd dist/_openai && zip -q -r -X "../../$OUT" "${PLUGIN}" )
rm -rf dist/_openai

echo
echo "== what is inside =="
unzip -Z1 "$OUT" | sed 's/^/  /'

# Exactly one top-level entry, and it is the plugin folder.
roots="$(unzip -Z1 "$OUT" | cut -d/ -f1 | sort -u)"
[ "$roots" = "$PLUGIN" ] || { echo "package_openai_plugin: the archive has more than the plugin root: $roots" >&2; exit 1; }
for required in "plugin.json" "mcp.json" ".mcp.json" "README.md" "LICENSE" ".claude-plugin/plugin.json" \
                ".codex-plugin/plugin.json" "skills/vyomi-setup/SKILL.md"; do
  unzip -Z1 "$OUT" | grep -qx "${PLUGIN}/${required}" || { echo "package_openai_plugin: $required is missing from the archive" >&2; exit 1; }
done
if unzip -Z1 "$OUT" | grep -qiE "(^|/)(hooks|\.git|node_modules)(/|$)"; then
  echo "package_openai_plugin: the archive contains hooks or git metadata" >&2; exit 1
fi

echo
echo "built $OUT ($(wc -c <"$OUT" | tr -d ' ') bytes, $(unzip -Z1 "$OUT" | wc -l | tr -d ' ') entries)"
echo "Submit this file; the listing fields come from ${PLUGIN}/plugin.json (extensions.com.openai.interface)."
echo "Set developerName to the verified OpenAI identity first (O-D1) — check_agent_plugins.py reports it while it is a placeholder."
