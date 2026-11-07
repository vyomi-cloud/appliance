#!/usr/bin/env bash
# Runner-side entrypoint for the remote-LLM spike (docs/architecture/v4.0/BOOSTER-RUNNER-LLM.md).
#
#   1. restore the models (actions/cache dir $MODEL_DIR, keyed by model hash) or download + sha256-verify them
#   2. start llama-server on 127.0.0.1 ONLY (chat + embeddings) with the same args as the in-Codespace AI pack
#   3. dial OUT to the relay with the runner-role session token (runner-llm-dial.mjs), heartbeat, serve
#   4. exit at TTL (<= 5h30m) or on SIGTERM (workflow cancel); always stop llama-server
#
# Public-repo logs are world-readable: this script never `set -x`, never echoes the token, URLs with credentials or request
# data; llama-server output goes to a file that is NEVER printed or uploaded.
#
# env (required): VYOMI_RELAY_URL  VYOMI_RUNNER_TOKEN
# env (optional): MODEL_DIR=/models  CHAT_FILE=chat.gguf  EMBED_FILE=embed.gguf
#                 CHAT_URL_SRC / CHAT_SHA256  EMBED_URL_SRC / EMBED_SHA256   (download fallback; sha256 REQUIRED to download)
#                 THREADS=4  CHAT_CTX=4096  TTL_S=19800  LLAMA_BIN=llama-server  WS_PKG  LLAMA_LOG=$RUNNER_TEMP/llama.log
set +x
set -uo pipefail

: "${VYOMI_RELAY_URL:?VYOMI_RELAY_URL required}"
: "${VYOMI_RUNNER_TOKEN:?VYOMI_RUNNER_TOKEN required}"
# Belt and braces: mask even if the workflow forgot (no-op outside Actions; the value is never printed).
[ -n "${GITHUB_ACTIONS:-}" ] && echo "::add-mask::${VYOMI_RUNNER_TOKEN}"

HERE="$(cd "$(dirname "$0")" && pwd)"
MODEL_DIR="${MODEL_DIR:-/models}"; CHAT_FILE="${CHAT_FILE:-chat.gguf}"; EMBED_FILE="${EMBED_FILE:-embed.gguf}"
THREADS="${THREADS:-4}"; CHAT_CTX="${CHAT_CTX:-4096}"; LLAMA_BIN="${LLAMA_BIN:-llama-server}"
TTL_S="${TTL_S:-19800}"; [ "$TTL_S" -gt 19800 ] && TTL_S=19800            # hard cap 5h30m (job cap is 6h)
LLAMA_LOG="${LLAMA_LOG:-${RUNNER_TEMP:-/tmp}/llama.log}"
CHAT_ALIAS="${CHAT_ALIAS:-qwen2.5-3b}"
CHAT_URL_SRC="${CHAT_URL_SRC:-https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf}"
EMBED_URL_SRC="${EMBED_URL_SRC:-https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/bge-small-en-v1.5-q8_0.gguf}"
mkdir -p "$MODEL_DIR"
T0=$(date +%s)
log() { echo "[runner-llm] $*"; }

sha_of() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

# restore_model <file> <src-url> <expected-sha256>
restore_model() {
  local f="$MODEL_DIR/$1" src="$2" want="${3:-}"
  if [ -f "$f" ] && { [ -z "$want" ] || [ "$(sha_of "$f")" = "$want" ]; }; then log "model $1: cache hit"; return 0; fi
  [ -f "$f" ] && { log "model $1: cached copy failed checksum, re-downloading"; rm -f "$f"; }
  [ -n "$want" ] || { log "model $1: not cached and no checksum configured - refusing to download an unverified model"; return 1; }
  log "model $1: cache miss, downloading"
  curl -fsSL --retry 3 -o "$f.part" "$src" || { log "model $1: download failed"; rm -f "$f.part"; return 1; }
  [ "$(sha_of "$f.part")" = "$want" ] || { log "model $1: CHECKSUM MISMATCH, discarding"; rm -f "$f.part"; return 1; }
  mv "$f.part" "$f"
}

restore_model "$CHAT_FILE" "$CHAT_URL_SRC" "${CHAT_SHA256:-}" || exit 3
restore_model "$EMBED_FILE" "$EMBED_URL_SRC" "${EMBED_SHA256:-}" || exit 3
log "models ready in $(( $(date +%s) - T0 ))s"

PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done; wait 2>/dev/null; }
trap 'log "cancelled"; cleanup; exit 0' TERM INT
trap cleanup EXIT

# Same args as codespace/.devcontainer/booster/docker-compose.booster.yml (llm-chat / llm-embed), loopback-bound.
"$LLAMA_BIN" -m "$MODEL_DIR/$CHAT_FILE" --host 127.0.0.1 --port 8080 -c "$CHAT_CTX" --jinja -np 1 --cache-reuse 256 \
  -t "$THREADS" --alias "$CHAT_ALIAS" >>"$LLAMA_LOG" 2>&1 &
PIDS+=($!)
"$LLAMA_BIN" -m "$MODEL_DIR/$EMBED_FILE" --host 127.0.0.1 --port 8081 --embeddings -c 512 -np 1 -t 1 >>"$LLAMA_LOG" 2>&1 &
PIDS+=($!)

export CHAT_URL="http://127.0.0.1:8080" EMBED_URL="http://127.0.0.1:8081" TTL_S
node "$HERE/runner-llm-dial.mjs" &
DIAL=$!; PIDS+=($DIAL)
wait "$DIAL"; rc=$?
log "dial ended (rc=$rc)"
exit "$rc"
