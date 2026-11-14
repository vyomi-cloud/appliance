#!/usr/bin/env bash
# Pre-release integration test for vyomi-tunnel 1.3.0 + the vyomi MCP + the Claude Code plugin.
# Builds exactly what tunnel-release.yml would publish, installs it in a throwaway prefix, and drives it
# against real homes on this machine. Nothing is published, released or installed globally.
#
#   tools/mcp-eval/prerelease-it.sh package   # build + npm pack + temp install + MCP handshake        (needs go, node, python3)
#   tools/mcp-eval/prerelease-it.sh linux     # install the tarball in node:20 containers, arm64 + amd64 (needs docker)
#   tools/mcp-eval/prerelease-it.sh brew      # local tap whose formula points at the tarball, then removed (needs brew)
#   tools/mcp-eval/prerelease-it.sh homes     # offline (:9000 if up), local mesh on :9100 (docker), fake Codespace
#   tools/mcp-eval/prerelease-it.sh nano      # real Nano tab: needs `vyomi-tunnel` running + a tab on vyomi.cloud/nano
#   tools/mcp-eval/prerelease-it.sh agent     # claude -p with --plugin-dir: scripted evals          (needs claude, signed in)
#   tools/mcp-eval/prerelease-it.sh all       # package linux brew homes agent (+ nano when a tab is connected)
#   tools/mcp-eval/prerelease-it.sh clean     # remove everything this script created
#
# Knobs (env): IT_DIR (default /tmp/vyomi-prerelease-it), IT_MESH_PORT (9100), IT_RUNS (agent repetitions, 1),
#   IT_MODEL (claude-opus-5-5), IT_KEEP_IMAGE=1 (keep the mesh image for the next run), IT_SKIP_BUILD=1 (reuse the tarball).
# Safety: it only stops/removes what it created (compose project vyomi-it-mesh, network vyomi-it-net, image
#   vyomi-it-mesh:local, tap vyomi/it, $IT_DIR). It never touches other containers, ~/.vyomi or ~/.claude settings.
# Written for macOS bash 3.2: no associative arrays, no ${x,,}, every array expansion guarded.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IT_DIR="${IT_DIR:-/tmp/vyomi-prerelease-it}"
PREFIX="$IT_DIR/prefix"
MESH_PORT="${IT_MESH_PORT:-9100}"
RUNS="${IT_RUNS:-1}"
MODEL="${IT_MODEL:-claude-opus-5-5}"
PLUGIN_DIR="$ROOT/integrations/claude-plugins/plugins/vyomi"
RESULTS="$IT_DIR/results.tsv"
DEAD_PORT=9            # nothing listens on the discard port: used to switch a home off for one check
mkdir -p "$IT_DIR"

# ---------- reporting ----------
say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
rec()  { # rec STAGE ID PASS|FAIL|SKIP|WARN "detail"
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$RESULTS"
  case "$3" in PASS) c=32 ;; FAIL) c=31 ;; WARN) c=33 ;; *) c=90 ;; esac
  printf '   \033[%sm%-4s\033[0m %-28s %s\n' "$c" "$3" "$2" "$4"
}
check() { # check STAGE ID "detail" <command...>   -> PASS if the command succeeds
  local st="$1" id="$2" d="$3"; shift 3
  if "$@" >>"$IT_DIR/log.txt" 2>&1; then rec "$st" "$id" PASS "$d"; return 0; fi
  rec "$st" "$id" FAIL "$d (see $IT_DIR/log.txt)"; return 1
}
have() { command -v "$1" >/dev/null 2>&1; }
need() { local st="$1"; shift; local m=""; for t in "$@"; do have "$t" || m="$m $t"; done
  [ -z "$m" ] && return 0; rec "$st" "prereq" SKIP "missing:$m"; return 1; }
summary() {
  say "Summary ($RESULTS)"
  [ -f "$RESULTS" ] || { note "no results"; return 0; }
  python3 - "$RESULTS" <<'EOF'
import sys, collections
rows=[l.rstrip("\n").split("\t") for l in open(sys.argv[1]) if l.strip()]
by=collections.OrderedDict()
for st,i,r,d in rows: by.setdefault(st,collections.Counter())[r]+=1
for st,c in by.items(): print(f"   {st:<8} " + "  ".join(f"{k} {c[k]}" for k in ("PASS","FAIL","WARN","SKIP") if c[k]))
fails=[(st,i,d) for st,i,r,d in rows if r=="FAIL"]
if fails:
    print("\n   FAILED:"); [print(f"   - {st}/{i}: {d}") for st,i,d in fails]
EOF
  ! grep -q $'\tFAIL\t' "$RESULTS"
}

# ---------- MCP over stdio (JSON-RPC lines) ----------
# mcp_session OUT [ENV=VAL ...] -- <tool> '<json args>' [<tool> '<json args>' ...]
# Starts `vyomi-tunnel mcp` from the temp prefix with the given env, sends initialize + calls, writes replies to OUT.
mcp_session() {
  local out="$1"; shift; local envs=()
  while [ $# -gt 0 ] && [ "$1" != "--" ]; do envs+=("$1"); shift; done; shift
  local i=10 req
  req='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"prerelease-it","version":"0"}}}'$'\n''{"jsonrpc":"2.0","method":"notifications/initialized"}'$'\n''{"jsonrpc":"2.0","id":2,"method":"tools/list"}'$'\n'
  while [ $# -ge 2 ]; do
    req="$req{\"jsonrpc\":\"2.0\",\"id\":$i,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}"$'\n'
    i=$((i+1)); shift 2
  done
  printf '%s' "$req" | env PATH="$PREFIX/bin:$PATH" ${envs[@]+"${envs[@]}"} "$PREFIX/bin/vyomi-tunnel" mcp >"$out" 2>"$out.err"
}
# jq-free JSON assertions (python3 is required anyway): js FILE 'python expr over r (dict id->reply), t(id) -> tool JSON'
js() { python3 - "$1" "$2" <<'EOF'
import json, sys
r = {}
for line in open(sys.argv[1]):
    line = line.strip()
    if not line: continue
    d = json.loads(line)                       # any non-JSON line on stdout fails here: stdout must be pure JSON-RPC
    if "id" in d: r[d["id"]] = d
def t(i):
    txt = r[i]["result"]["content"][0]["text"]
    try: return json.loads(txt)
    except ValueError: return txt
ok = eval(sys.argv[2], {"r": r, "t": t, "json": json})
sys.exit(0 if ok else 1)
EOF
}

# ---------- stages ----------
stage_package() {
  say "package: build what tunnel-release.yml publishes, install it in $PREFIX"
  local tgz
  if [ "${IT_SKIP_BUILD:-}" = "1" ] && ls "$IT_DIR"/vyomi-tunnel-*.tgz >/dev/null 2>&1; then
    need package node npm python3 || return 0
    note "IT_SKIP_BUILD=1: reusing $(ls "$IT_DIR"/vyomi-tunnel-*.tgz)"
  else
    need package go node npm python3 || return 0
    rm -f "$IT_DIR"/vyomi-tunnel-*.tgz
    check package build "scripts/build_tunnel_mcp.sh (5 binaries)" bash "$ROOT/scripts/build_tunnel_mcp.sh" || return 0
    check package pack "npm pack" sh -c "cd '$ROOT/packaging/tunnel' && npm pack --pack-destination '$IT_DIR' --json > '$IT_DIR/pack.json'" || return 0
  fi
  tgz="$(ls "$IT_DIR"/vyomi-tunnel-*.tgz | head -1)"
  check package tracked-clean "build left no tracked changes" sh -c "cd '$ROOT' && test -z \"\$(git status --porcelain --untracked-files=no)\""
  check package tarball-binaries "tarball has the 5 bundled binaries" sh -c \
    "tar tzf '$tgz' | grep -cE 'package/mcp/(darwin-arm64|darwin-x64|linux-arm64|linux-x64)/vyomi-mcp\$|package/mcp/win32-x64/vyomi-mcp.exe\$' | grep -qx 5"
  local bytes; bytes=$(wc -c < "$tgz" | tr -d ' ')
  if [ "$bytes" -le $((25*1024*1024)) ]; then rec package size PASS "$((bytes/1024/1024)) MiB <= 25 MiB guard"
  else rec package size FAIL "$((bytes/1024/1024)) MiB > 25 MiB guard"; fi
  rm -rf "$PREFIX"
  check package install "npm i -g --prefix $PREFIX" npm i -g --prefix "$PREFIX" "$tgz" || return 0
  check package version "vyomi-tunnel --version = the tarball's package.json" sh -c \
    "'$PREFIX/bin/vyomi-tunnel' --version | grep -qF \"vyomi-tunnel \$(node -p \"require('$PREFIX/lib/node_modules/vyomi-tunnel/package.json').version\")\""
  local plat; plat="$(node -p 'process.platform+"-"+process.arch')"
  check package exec-bit "bundled mcp/$plat binary is executable" sh -c \
    "test -x \"\$(ls -d '$PREFIX'/lib/node_modules/vyomi-tunnel/mcp/$plat/vyomi-mcp*)\""
  local o="$IT_DIR/mcp-package.jsonl"
  mcp_session "$o" HOME="$IT_DIR/home-empty" -- vyomi_capability '{"query":"aks.cluster"}'
  check package mcp-handshake "initialize + tools/list, pure JSON-RPC stdout" js "$o" \
    'r[1]["result"]["serverInfo"]["name"]=="vyomi" and len(r[2]["result"]["tools"])>=8'
  check package mcp-no-key "works with no ~/.vyomi credentials (empty HOME)" js "$o" \
    '"mesh" in json.dumps(t(10)).lower()'
}

stage_linux() {
  say "linux: install the same tarball in node:20 containers"
  need linux docker || return 0
  docker info >/dev/null 2>&1 || { rec linux prereq SKIP "docker daemon not running"; return 0; }
  local tgz; tgz="$(ls "$IT_DIR"/vyomi-tunnel-*.tgz 2>/dev/null | head -1)"
  [ -n "$tgz" ] || { rec linux prereq SKIP "no tarball: run the package stage first"; return 0; }
  local p
  for p in linux/arm64 linux/amd64; do
    check linux "install-$p" "npm i -g + vyomi-tunnel mcp initialize ($p)" sh -c \
      "printf '%s\n' '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"it\",\"version\":\"0\"}}}' \
       | docker run --rm -i --platform $p -v '$IT_DIR':/it:ro node:20-slim sh -c 'npm i -g /it/$(basename "$tgz") >/dev/null 2>&1 && vyomi-tunnel mcp 2>/dev/null' \
       | grep -q '\"serverInfo\":{[^}]*\"name\":\"vyomi\"'"
  done
}

stage_brew() {
  say "brew: a throwaway tap whose formula installs the local tarball"
  need brew brew || return 0
  local tgz; tgz="$(ls "$IT_DIR"/vyomi-tunnel-*.tgz 2>/dev/null | head -1)"
  [ -n "$tgz" ] || { rec brew prereq SKIP "no tarball: run the package stage first"; return 0; }
  if brew list --formula 2>/dev/null | grep -qx vyomi-tunnel && ! brew list --formula vyomi/it/vyomi-tunnel >/dev/null 2>&1; then
    rec brew prereq SKIP "a vyomi-tunnel formula is already installed (brew uninstall it first to run this stage)"; return 0
  fi
  local ver sha tapdir
  ver="$(basename "$tgz" .tgz | sed 's/^vyomi-tunnel-//')"; sha="$(shasum -a 256 "$tgz" | cut -d' ' -f1)"
  export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_FROM_API=1 HOMEBREW_NO_ENV_HINTS=1
  brew untap vyomi/it >/dev/null 2>&1 || true
  check brew tap "brew tap-new vyomi/it" brew tap-new --no-git vyomi/it || return 0
  tapdir="$(brew --repository)/Library/Taps/vyomi/homebrew-it"
  mkdir -p "$tapdir/Formula"
  python3 - "$ROOT/packaging/brew/vyomi-tunnel.rb" "$tapdir/Formula/vyomi-tunnel.rb" "$tgz" "$sha" "$ver" <<'EOF'
import re, sys
src, dst, tgz, sha, ver = sys.argv[1:]
f = open(src).read()
f = re.sub(r'(?m)^  url .*$', f'  url "file://{tgz}"', f)
f = re.sub(r'(?m)^  sha256 .*$', f'  sha256 "{sha}"\n  version "{ver}"', f)
open(dst, "w").write(f)
EOF
  if check brew install "brew install vyomi/it/vyomi-tunnel ($ver)" brew install vyomi/it/vyomi-tunnel; then
    local o="$IT_DIR/mcp-brew.jsonl" bp; bp="$(brew --prefix)/bin/vyomi-tunnel"
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"it","version":"0"}}}' \
      | "$bp" mcp >"$o" 2>/dev/null
    check brew mcp "brew-installed vyomi-tunnel mcp answers" js "$o" 'r[1]["result"]["serverInfo"]["name"]=="vyomi"'
    if brew test vyomi/it/vyomi-tunnel >>"$IT_DIR/log.txt" 2>&1; then rec brew formula-test PASS "brew test"
    else rec brew formula-test FAIL "brew test (formula test block: --version + mcp initialize)"; fi
    brew uninstall --formula vyomi/it/vyomi-tunnel >>"$IT_DIR/log.txt" 2>&1
  fi
  brew untap vyomi/it >>"$IT_DIR/log.txt" 2>&1 && note "removed tap vyomi/it"
}

fake_tunnel() { # a stand-in vyomi-tunnel whose `list mesh --json` replays the row run 3 recorded from a real mesh container
  local f="$IT_DIR/fake-tunnel.sh"
  cat > "$f" <<'EOF'
#!/bin/sh
case "$*" in
  *list*--json*|*--json*list*) cat <<'J'
{"schema":1,"rows":[{"where":"mesh","name":"host","type":"host","address":"codespace","connect":"ssh vyomi-mesh"},{"where":"mesh","name":"vyomi-mesh-simulator-1","type":"service","address":"172.23.0.2:9000","connect":"vyomi-tunnel forward vyomi-mesh-simulator-1 9000:9000"}],"notes":[]}
J
  ;;
  *--version*) echo "1.3.0" ;;
  *) exit 1 ;;
esac
EOF
  chmod +x "$f"; printf '%s' "$f"
}

stage_homes() {
  say "homes: offline (:9000 if up), local mesh (:$MESH_PORT), Codespace (fake tunnel)"
  [ -x "$PREFIX/bin/vyomi-tunnel" ] || { rec homes prereq SKIP "run the package stage first"; return 0; }
  local o
  # offline: only if something non-mesh answers on :9000 (e.g. your vyomi 3.x stack)
  if curl -fsS --max-time 2 http://127.0.0.1:9000/healthz >/dev/null 2>&1 \
     && ! curl -fsS --max-time 2 http://127.0.0.1:9000/mesh/status 2>/dev/null | grep -q '"mesh": *true'; then
    o="$IT_DIR/mcp-offline.jsonl"
    mcp_session "$o" RELAY_PORT=$DEAD_PORT VYOMI_TUNNEL_BIN=/nonexistent -- vyomi_status '{}' vyomi_env '{"cloud":"aws","lang":"python"}'
    check homes offline-selected "offline appliance on :9000 selected" js "$o" 't(10)["selected"]["id"]=="offline" if isinstance(t(10).get("selected"),dict) else t(10).get("selected")=="offline"'
    check homes offline-env "offline env points at :9000" js "$o" '"127.0.0.1:9000" in json.dumps(t(11))'
  else rec homes offline SKIP "nothing non-mesh on :9000"; fi

  # Codespace mesh, via a fake tunnel (real Codespace only after Mesh go-live)
  local ft; ft="$(fake_tunnel)"; o="$IT_DIR/mcp-codespace.jsonl"
  mcp_session "$o" RELAY_PORT=$DEAD_PORT VYOMI_SIMULATOR_PORT=$DEAD_PORT VYOMI_MESH_URL=http://127.0.0.1:$DEAD_PORT VYOMI_TUNNEL_BIN="$ft" \
    VYOMI_ACCESS_KEY_ID=it-dummy-presence-only -- vyomi_status '{}' vyomi_reach '{"scope":"mesh"}' \
    vyomi_env '{"cloud":"aws","lang":"python","home":"mesh"}'
  check homes codespace-detected "Codespace home reachable via the tunnel's list" js "$o" \
    'any(h["id"]=="mesh-codespace" and h["reachable"] for h in t(10)["homes"])'
  check homes codespace-reach "vyomi_reach lists the appliance row" js "$o" '"vyomi-mesh-simulator-1" in json.dumps(t(11))'
  check homes codespace-forward-hint "hint gives the forward command on a free local port, for the user to run" js "$o" \
    '__import__("re").search(r"vyomi-tunnel forward vyomi-mesh-simulator-1 \d+:9000", json.dumps(t(10))) and "do not run it yourself" in json.dumps(t(10))'
  check homes codespace-env "home=mesh env is the Codespace (not mesh-local, not the dead VYOMI_MESH_URL)" js "$o" \
    '"mesh-codespace" in json.dumps(t(12)) and "mesh-local" not in json.dumps(t(12)) and "127.0.0.1:9\"" not in json.dumps(t(12)) and "never starts forwards" in json.dumps(t(12))'

  # local mesh: the branch's image, run as a mesh on :$MESH_PORT
  if ! have docker || ! docker info >/dev/null 2>&1; then rec homes mesh SKIP "docker not available"; return 0; fi
  local img=vyomi-it-mesh:local proj=vyomi-it-mesh ov="$IT_DIR/mesh-override.yml" envf="$IT_DIR/mesh.env"
  if ! docker image inspect "$img" >/dev/null 2>&1; then
    check homes mesh-image "docker build the branch image (several minutes)" docker build -t "$img" "$ROOT" || return 0
  fi
  cat > "$ov" <<EOF
networks:
  vyomi-net:
    name: vyomi-it-net
services:
  simulator:
    image: $img
    pull_policy: never
    ports: ["127.0.0.1:$MESH_PORT:9000"]
    environment:
      VYOMI_INSTANCE_NETWORK: vyomi-it-net
EOF
  python3 - "$ROOT" > "$envf" <<'EOF'
import sys, time, secrets
sys.path.insert(0, sys.argv[1]); from core.mesh_session import mint
k = secrets.token_hex(32)
print("VYOMI_MESH_SESSION_KEY=" + k); print("VYOMI_MESH_SESSION_TOKEN=" + mint("local-max", "max", time.time() + 8 * 3600, key=k))
EOF
  chmod 600 "$envf"
  check homes mesh-up "compose up ($proj, :$MESH_PORT)" docker compose -p "$proj" --env-file "$envf" \
    -f "$ROOT/codespace/.devcontainer/mesh/docker-compose.mesh.yml" -f "$ov" up -d --pull never simulator || { stage_homes_down; return 0; }
  local n=0; until curl -fsS --max-time 2 "http://127.0.0.1:$MESH_PORT/mesh/status" 2>/dev/null | grep -q '"mesh": *true'; do
    n=$((n+1)); [ $n -ge 60 ] && break; sleep 3; done
  if [ $n -ge 60 ]; then rec homes mesh-status FAIL "/mesh/status never said mesh:true"; stage_homes_down; return 0; fi
  rec homes mesh-status PASS "/mesh/status mesh:true on :$MESH_PORT"
  o="$IT_DIR/mcp-mesh.jsonl"
  mcp_session "$o" RELAY_PORT=$DEAD_PORT VYOMI_SIMULATOR_PORT=$DEAD_PORT VYOMI_MESH_URL="http://127.0.0.1:$MESH_PORT" VYOMI_TUNNEL_BIN=/nonexistent \
    -- vyomi_status '{}' vyomi_env "{\"cloud\":\"aws\",\"lang\":\"python\",\"home\":\"mesh\"}"
  check homes mesh-selected "local mesh selected" js "$o" '"mesh-local" in json.dumps(t(10).get("selected"))'
  check homes mesh-env "mesh env points at :$MESH_PORT" js "$o" "'127.0.0.1:$MESH_PORT' in json.dumps(t(11))"
  if have aws; then
    check homes mesh-s3 "aws s3 mb/ls against the mesh" sh -c \
      "export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=''; \
       aws --endpoint-url http://127.0.0.1:$MESH_PORT s3 mb s3://it-mesh-$$ && aws --endpoint-url http://127.0.0.1:$MESH_PORT s3 ls | grep -q it-mesh-$$"
  fi
  stage_homes_down
}
stage_homes_down() {
  docker compose -p vyomi-it-mesh -f "$ROOT/codespace/.devcontainer/mesh/docker-compose.mesh.yml" -f "$IT_DIR/mesh-override.yml" \
    down -v >>"$IT_DIR/log.txt" 2>&1 && note "removed compose project vyomi-it-mesh (container, volume, network)"
  rm -f "$IT_DIR/mesh.env"
  [ "${IT_KEEP_IMAGE:-}" = "1" ] || { docker rmi vyomi-it-mesh:local >>"$IT_DIR/log.txt" 2>&1 && note "removed image vyomi-it-mesh:local"; }
}

nano_up() { curl -fsS --max-time 2 http://127.0.0.1:8090/health 2>/dev/null | grep -q '"tab": *true'; }
stage_nano() {
  say "nano: the real Nano tab through the tunnel on :8090"
  [ -x "$PREFIX/bin/vyomi-tunnel" ] || { rec nano prereq SKIP "run the package stage first"; return 0; }
  nano_up || { rec nano prereq SKIP "no tab: run \`vyomi-tunnel\` (1.3.0) and open https://vyomi.cloud/nano"; return 0; }
  check nano list-json "vyomi-tunnel list nano --json: schema 1 + api row" sh -c \
    "'$PREFIX/bin/vyomi-tunnel' list nano --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d[\"schema\"]==1 and any(r[\"type\"]==\"api\" for r in d[\"rows\"])'"
  local o="$IT_DIR/mcp-nano.jsonl"
  mcp_session "$o" VYOMI_TARGET=nano -- vyomi_status '{}' vyomi_env '{"cloud":"aws","lang":"python","home":"nano"}' \
    vyomi_env '{"cloud":"azure","lang":"python","home":"nano"}' vyomi_snippet '{"cloud":"aws","service":"s3","lang":"python","home":"nano"}'
  check nano selected "nano-local selected, tab connected" js "$o" '"nano-local" in json.dumps(t(10).get("selected"))'
  check nano env-aws "AWS env on :8090, nothing on :9000/:9443" js "$o" \
    '"127.0.0.1:8090" in json.dumps(t(11)) and ":9000" not in json.dumps(t(11)) and ":9443" not in json.dumps(t(11))'
  check nano env-keyvault "Azure env warns Key Vault is not available via the tunnel" js "$o" '"key vault" in json.dumps(t(12)).lower()'
  check nano snippet "S3 snippet aimed at :8090" js "$o" '"127.0.0.1:8090" in json.dumps(t(13))'
  if have aws; then
    check nano s3 "aws s3 mb/ls/rb against the tab" sh -c \
      "export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=''; E=http://127.0.0.1:8090; \
       aws --endpoint-url \$E s3 mb s3://it-nano-$$ && aws --endpoint-url \$E s3 ls | grep -q it-nano-$$ && aws --endpoint-url \$E s3 rb s3://it-nano-$$"
  fi
}

# ---------- agent evals: real Claude Code + the plugin from this branch ----------
fixture() { # fixture NAME KIND -> path of a fresh throwaway project
  local d="$IT_DIR/fixtures/$1"; rm -rf "$d"; mkdir -p "$d"
  case "$2" in
    aws)   printf 'import boto3\ns3 = boto3.client("s3")\ns3.create_bucket(Bucket="orders")\n' > "$d/app.py"
           printf 'boto3\n' > "$d/requirements.txt" ;;
    aks)   printf 'import boto3\nfrom azure.mgmt.containerservice import ContainerServiceClient\n' > "$d/deploy.py" ;;
  esac
  (cd "$d" && git init -q && git add -A && git -c user.email=it@local -c user.name=it commit -qm fixture)
  printf '%s' "$d"
}
# eval_run ID FIXTURE PROMPT CHECK [ENV=VAL ...]  -> runs claude -p in FIXTURE, CHECK is python over: tools (names),
#   bash (commands), text (final answer, lowercased), env_file (contents of .env.vyomi or "")
eval_run() {
  local id="$1" dir="$2" prompt="$3" chk="$4"; shift 4
  local k pass=0 log
  for k in $(seq 1 "$RUNS"); do
    log="$IT_DIR/agent-$id-$k.jsonl"; rm -f "$dir/.env.vyomi"
    (cd "$dir" && env PATH="$PREFIX/bin:$PATH" ${1+"$@"} claude -p "$prompt" --plugin-dir "$PLUGIN_DIR" --model "$MODEL" \
      --permission-mode auto --permission-prompts none --max-turns 30 --output-format stream-json --verbose >"$log" 2>&1)
    if python3 - "$log" "$dir/.env.vyomi" "$chk" <<'EOF'
import json, os, sys
tools, bash, text = [], [], ""
for line in open(sys.argv[1]):
    try: d = json.loads(line)
    except ValueError: continue
    if d.get("type") == "assistant":
        for b in d.get("message", {}).get("content", []):
            if b.get("type") == "tool_use":
                tools.append(b["name"]);
                if b["name"] == "Bash": bash.append(b.get("input", {}).get("command", ""))
    if d.get("type") == "result": text = str(d.get("result", "")).lower()
env_file = open(sys.argv[2]).read() if os.path.exists(sys.argv[2]) else ""
called = lambda name: any(t.endswith("__" + name) for t in tools)
sys.exit(0 if eval(sys.argv[3], {"tools": tools, "bash": bash, "text": text, "env_file": env_file, "called": called}) else 1)
EOF
    then pass=$((pass+1)); fi
  done
  if [ "$pass" -eq "$RUNS" ]; then rec agent "$id" PASS "$pass/$RUNS runs"
  else rec agent "$id" FAIL "$pass/$RUNS runs (logs: $IT_DIR/agent-$id-*.jsonl)"; fi
}
stage_agent() {
  say "agent: claude -p with --plugin-dir $PLUGIN_DIR (model $MODEL, $RUNS run(s) each)"
  need agent claude python3 || return 0
  [ -x "$PREFIX/bin/vyomi-tunnel" ] || { rec agent prereq SKIP "run the package stage first"; return 0; }
  check agent plugin-validate "claude plugin validate" claude plugin validate "$ROOT/integrations/claude-plugins"
  local ft; ft="$(fake_tunnel)"
  local off="RELAY_PORT=$DEAD_PORT VYOMI_SIMULATOR_PORT=$DEAD_PORT VYOMI_MESH_URL=http://127.0.0.1:$DEAD_PORT VYOMI_TUNNEL_BIN=/nonexistent"
  local aws; aws="$(fixture aws aws)"
  # A-02: nothing running -> Nano onboarding, no `vyomi up`, nothing written
  # shellcheck disable=SC2086
  eval_run A02-nothing-running "$aws" "Set this project up to run against Vyomi." \
    'called("vyomi_status") and ("vyomi-tunnel" in text or "vyomi.cloud/nano" in text) and "vyomi up" not in text and env_file==""' $off
  # A-06: Codespace mesh -> proposes the forward, never runs it
  # shellcheck disable=SC2086
  eval_run A06-codespace "$aws" "Use my Mesh Codespace for this project's AWS calls." \
    'called("vyomi_status") and "vyomi-tunnel forward" in text and not any("forward" in c for c in bash)' \
    RELAY_PORT=$DEAD_PORT VYOMI_SIMULATOR_PORT=$DEAD_PORT VYOMI_MESH_URL=http://127.0.0.1:$DEAD_PORT VYOMI_TUNNEL_BIN="$ft" VYOMI_ACCESS_KEY_ID=it-dummy-presence-only
  if nano_up; then
    # A-01: Nano -> :8090 env, asks before writing
    eval_run A01-nano-ask "$aws" "Set this project up to run against Vyomi, using the Nano tab." \
      'called("vyomi_status") and "8090" in text and "vyomi up" not in text and env_file==""' \
      VYOMI_SIMULATOR_PORT=$DEAD_PORT
    # A-01b: explicit go-ahead -> writes .env.vyomi with the nano header
    eval_run A01b-nano-write "$aws" "Write a .env.vyomi in this folder for the AWS SDK using the Vyomi Nano tab. Yes, write it now." \
      'called("vyomi_write_env") and "nano-local" in env_file and "127.0.0.1:8090" in env_file and ":9000" not in env_file' \
      VYOMI_SIMULATOR_PORT=$DEAD_PORT
    # A-05: mesh-only feature on Nano
    eval_run A05-aks-on-nano "$(fixture aks aks)" "Can I test this project on Vyomi using the Nano tab?" \
      '("mesh" in text) and ("pro" in text or "max" in text) and env_file==""' VYOMI_SIMULATOR_PORT=$DEAD_PORT
    if curl -fsS --max-time 2 http://127.0.0.1:9000/healthz >/dev/null 2>&1; then
      # A-03: two homes -> asks which, writes nothing
      eval_run A03-ambiguous "$aws" "Set this project up to run against Vyomi." \
        'called("vyomi_status") and "nano" in text and ("offline" in text or "appliance" in text or "9000" in text) and env_file==""'
    else rec agent A03-ambiguous SKIP "needs a second home on :9000"; fi
  else
    for k in A01-nano-ask A01b-nano-write A05-aks-on-nano A03-ambiguous; do rec agent "$k" SKIP "no Nano tab connected"; done
  fi
}

stage_clean() {
  say "clean"
  if have docker && docker info >/dev/null 2>&1; then
    [ -f "$IT_DIR/mesh-override.yml" ] || printf 'services: {}\n' > "$IT_DIR/mesh-override.yml"
    stage_homes_down
  fi
  if have brew; then brew untap vyomi/it >/dev/null 2>&1 && note "removed tap vyomi/it"; fi
  rm -rf "$IT_DIR" && note "removed $IT_DIR"
}

# ---------- main ----------
cmd="${1:-all}"
# `all` starts a fresh results file; a single stage replaces only its own rows, so stages run one by one add up.
case "$cmd" in
  all) : > "$RESULTS" ;;
  package|linux|brew|homes|nano|agent)
    if [ -f "$RESULTS" ]; then grep -v "^$cmd"$'\t' "$RESULTS" > "$RESULTS.tmp" || true; mv "$RESULTS.tmp" "$RESULTS"; fi ;;
esac
case "$cmd" in
  package) stage_package ;;
  linux)   stage_linux ;;
  brew)    stage_brew ;;
  homes)   stage_homes ;;
  nano)    stage_nano ;;
  agent)   stage_agent ;;
  all)     stage_package; stage_linux; stage_brew; stage_homes; if nano_up; then stage_nano; else rec nano prereq SKIP "no tab connected"; fi; stage_agent ;;
  clean)   stage_clean; exit 0 ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
summary
