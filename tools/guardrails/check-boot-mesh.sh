#!/usr/bin/env bash
# Behaviour check for a Mesh boot script's session-token handling (docs/architecture/v4.0/MESH-SESSION-ED25519.md).
#
#   bash tools/guardrails/check-boot-mesh.sh <path/to/boot-mesh.sh>
#
# Runs the script's own token_usable + fetch_session against a stubbed portal (no network, no Docker) and requires:
#   1. a v2 token with NO key is accepted on the first try   (2026-11-22: sandbox still required the v1 key; every Mesh looped)
#   2. a v1 token WITH its key is accepted                   (v1 keeps working until V1_ACCEPTED = False)
#   3. a v1 token without its key is refused                 (fails closed)
#   4. neither the token nor the key ever appears in the script's log output, and no log/echo line expands them
#      (2026-11-22: the "not a working Mesh" error printed the token after "present")
# Used by tools/guardrails/run.sh on the appliance copy (codespace/.devcontainer/mesh/boot-mesh.sh) and, in CI, on the copy
# Codespaces actually boot (vyomi-cloud/sandbox .devcontainer/mesh/boot-mesh.sh).
set -uo pipefail
f="${1:?usage: check-boot-mesh.sh <boot-mesh.sh>}"
[ -f "$f" ] || { echo "no such file: $f"; exit 1; }
rc=0
ok()  { echo "ok    $*"; }
bad() { echo "FAIL  $*"; rc=1; }

grep -q '^token_usable()' "$f" || bad "token_usable() is missing (the v2-or-v1-with-key rule)"
grep -q '^fetch_session() {' "$f" || { bad "fetch_session() is missing"; exit 1; }

TOK_V2='v2.eyJraWQiOiJndWFyZHJhaWwifQ.c2lnbmF0dXJlLWd1YXJkcmFpbA'
TOK_V1='v1.eyJzZXNzaW9uX2lkIjoiZ3VhcmRyYWlsIn0.aG1hYy1ndWFyZHJhaWw'
KEY='ffeeddccbbaa99887766554433221100guardrailkey'

# probe <body> -> prints "rc=<n> token=<prefix|none>" then the log lines; runs the script's functions in a clean shell.
probe() {
  BODY="$1" F="$f" bash -c '
    log() { echo "[log] $*"; }; curl() { printf "%s\n200" "$BODY"; }; sleep() { :; }
    PORTAL=http://portal.invalid CODESPACE=cs-guardrail VYOMI_MESH_TOKEN_TRIES=2
    unset VYOMI_MESH_SESSION_TOKEN VYOMI_MESH_SESSION_KEY VYOMI_MESH_SESSION_END
    eval "$(sed -n "/^token_usable()/p; /^fetch_session() {/,/^}/p" "$F")"
    fetch_session; r=$?
    echo "rc=$r token=${VYOMI_MESH_SESSION_TOKEN:+${VYOMI_MESH_SESSION_TOKEN%%.*}}"' 2>&1
}
body() { printf '{"token": "%s", %s"relay_url": "", "session_end": 1800000000}' "$1" "${2:+\"key\": \"$2\", }"; }

out="$(probe "$(body "$TOK_V2")")"
case "$out" in *"rc=0 token=v2"*) ok "keyless v2 token accepted";; *) bad "keyless v2 token NOT accepted: $(echo "$out" | tail -3 | tr '\n' ' ')";; esac
[ "$(echo "$out" | grep -c '^\[log\].*HTTP 200 but no token')" = 0 ] || bad "v2 accepted only after retries"
all="$out"

out="$(probe "$(body "$TOK_V1" "$KEY")")"
case "$out" in *"rc=0 token=v1"*) ok "v1 token with key accepted";; *) bad "v1 token with key NOT accepted";; esac
all="$all
$out"

out="$(probe "$(body "$TOK_V1")")"
if echo "$out" | grep -q '^rc=1 token=$'; then ok "v1 token without key refused"; else bad "v1 token without key was accepted"; fi
all="$all
$out"

if echo "$all" | grep -F -e "$TOK_V2" -e "$TOK_V1" -e "$KEY" -e "c2lnbmF0dXJl" -e "aG1hYy1n" >/dev/null; then
  bad "the token or key appeared in the log output"
else
  ok "token and key never logged by fetch_session"
fi

# Static: a log/echo line may test the token's presence ([ -n "${VYOMI_MESH_SESSION_TOKEN:-}" ]) and print the version prefix
# (${tok%%.*}), never the value. Catches leaks on paths the probe cannot reach (e.g. the "not a working Mesh" error).
leaks="$(grep -nE '^[[:space:]]*(log|echo|printf)[[:space:]]' "$f" \
  | sed -E 's/\[ -n "\$\{VYOMI_MESH_SESSION_(TOKEN|KEY):-\}" \]//g; s/\$\{tok%%\.\*\}//g' \
  | grep -E 'VYOMI_MESH_SESSION_(TOKEN|KEY)|\$\{?(tok|key)\b' || true)"
if [ -n "$leaks" ]; then bad "log/echo lines that can print the token or key:"; echo "$leaks" | sed 's/^/        /'; else ok "no log/echo line expands the token or key"; fi

exit "$rc"
