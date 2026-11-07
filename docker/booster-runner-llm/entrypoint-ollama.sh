#!/usr/bin/env bash
# Runner entrypoint, OLLAMA runtime (one model per runner; see docs/architecture/v4.0/BOOSTER-RUNNER-LLM.md).
#   1. `ollama serve` on 127.0.0.1 only, models dir = $MODEL_DIR (the actions/cache path, keyed by the model's ollama tag)
#   2. `ollama pull $OLLAMA_TAG` - a cache hit is a manifest check (no blob download); a miss pulls from registry.ollama.ai,
#      and ollama itself verifies every blob's sha256 against the manifest. If MODEL_DIGEST (sha256 of the manifest, from the
#      portal catalogue) is given it must match `ollama show` digest, else we refuse to serve.
#   3. warm the model (load + keep_alive -1), then dial OUT to the relay (runner-llm-dial.mjs: proxies OpenAI /v1/* and Ollama
#      /api/* to the single local server), heartbeat, exit at TTL (<= 5h30m) or SIGTERM.
# Public-repo logs are world-readable: no `set -x`, no token/prompt echo; ollama's log goes to a file that is never printed.
#
# env (required): VYOMI_RELAY_URL VYOMI_RUNNER_TOKEN OLLAMA_TAGS (e.g. "qwen2.5:3b-instruct-q4_K_M,nomic-embed-text:latest")
# env (optional): MODEL_DIR=$HOME/.ollama/models  TTL_S=19800  OLLAMA_BIN=ollama  WS_PKG  MODEL_DIGEST  THREADS=4
set +x
set -uo pipefail
: "${VYOMI_RELAY_URL:?}" "${VYOMI_RUNNER_TOKEN:?}" "${OLLAMA_TAGS:?comma-separated ollama tags}"
[ -n "${GITHUB_ACTIONS:-}" ] && echo "::add-mask::${VYOMI_RUNNER_TOKEN}"
HERE="$(cd "$(dirname "$0")" && pwd)"
OLLAMA_BIN="${OLLAMA_BIN:-ollama}"
export OLLAMA_MODELS="${MODEL_DIR:-$HOME/.ollama/models}" OLLAMA_HOST="127.0.0.1:11434" OLLAMA_KEEP_ALIVE="-1" OLLAMA_NUM_PARALLEL="1" \
       OLLAMA_MAX_LOADED_MODELS="2" OLLAMA_NUM_THREAD="${THREADS:-4}" OLLAMA_NOPRUNE="1"
TTL_S="${TTL_S:-21000}"; [ "$TTL_S" -gt 21000 ] && TTL_S=21000       # 5h50m < 6h job cap; the booster rotates at 5h30m
LOG="${LLAMA_LOG:-${RUNNER_TEMP:-/tmp}/ollama.log}"
mkdir -p "$OLLAMA_MODELS"; T0=$(date +%s)
log() { echo "[runner-ollama] $*"; }

PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done; wait 2>/dev/null; }
trap 'log "cancelled"; cleanup; exit 0' TERM INT
trap cleanup EXIT

"$OLLAMA_BIN" serve >>"$LOG" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 60); do curl -sf "http://$OLLAMA_HOST/api/version" >/dev/null && break; sleep 1; done
curl -sf "http://$OLLAMA_HOST/api/version" >/dev/null || { log "ollama did not start"; exit 3; }

before=$(du -sm "$OLLAMA_MODELS" 2>/dev/null | cut -f1)
IFS=',' read -r -a TAGS <<<"$OLLAMA_TAGS"
for t in "${TAGS[@]}"; do "$OLLAMA_BIN" pull "$t" >>"$LOG" 2>&1 || { log "pull failed"; exit 3; }; done
OLLAMA_TAG="${TAGS[0]}"
after=$(du -sm "$OLLAMA_MODELS" 2>/dev/null | cut -f1)
log "model present ($([ "${after:-0}" -gt "${before:-0}" ] && echo "pulled $(( ${after:-0} - ${before:-0} )) MB" || echo "cache hit")) in $(( $(date +%s) - T0 ))s"
if [ -n "${MODEL_DIGEST:-}" ]; then
  got=$("$OLLAMA_BIN" show "$OLLAMA_TAG" --modelfile 2>/dev/null | sed -n 's/^FROM .*sha256-\([0-9a-f]\{64\}\).*/\1/p' | head -1)
  [ "$got" = "$MODEL_DIGEST" ] || { log "DIGEST MISMATCH - refusing to serve"; exit 3; }
fi
# warm: load every tag into RAM and pin it (empty prompt = load only; embedding models via /api/embed)
for t in "${TAGS[@]}"; do
  curl -sf "http://$OLLAMA_HOST/api/generate" -d "{\"model\":\"$t\",\"prompt\":\"\",\"keep_alive\":-1}" >/dev/null \
    || curl -sf "http://$OLLAMA_HOST/api/embed" -d "{\"model\":\"$t\",\"input\":\"warm\",\"keep_alive\":-1}" >/dev/null || log "warm-up of a model failed (continuing)"
done
log "warm in $(( $(date +%s) - T0 ))s"

# ollama serves OpenAI (/v1/*) AND native (/api/*) on one port: chat and embed URLs are the same upstream.
export CHAT_URL="http://$OLLAMA_HOST" EMBED_URL="http://$OLLAMA_HOST" TTL_S
node "$HERE/runner-llm-dial.mjs" &
DIAL=$!; PIDS+=($DIAL)
wait "$DIAL"; rc=$?
log "dial ended (rc=$rc)"
exit "$rc"
