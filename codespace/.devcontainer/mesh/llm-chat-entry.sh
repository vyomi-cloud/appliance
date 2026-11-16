#!/bin/sh
# llm-chat entrypoint: llama-server + chat-LoRA hot-reload without a docker socket.
# llama-server loads LoRA adapters only at START (--lora-scaled <file>:0; a request opts in with lora:[{id,scale}]). The appliance writes a trained
# adapter to <mesh-data>/llm-adapters/<id>.gguf (core/llm_core.lora_prepare). This wrapper watches that directory (read-only mount) and, when the
# set of *.gguf files changes, restarts ONLY llama-server inside the container with the new --lora-scaled list. Args = the llama-server args.
D="${VYOMI_LLM_ADAPTER_DIR:-/data/llm-adapters}"; BIN="${LLAMA_BIN:-/app/llama-server}"; EVERY="${VYOMI_LLM_ADAPTER_POLL:-10}"
sig() { for f in "$D"/*.gguf; do [ -f "$f" ] && echo "${f##*/} $(wc -c < "$f" | tr -d ' ')"; done | sort; }
PID=""; trap '[ -n "$PID" ] && kill "$PID" 2>/dev/null; exit 0' TERM INT
while :; do
  S="$(sig)"
  [ -n "$S" ] && echo "llm-chat-entry: loading adapters: $(printf '%s' "$S" | cut -d' ' -f1 | tr '\n' ' ')"
  ( for f in $(printf '%s\n' "$S" | cut -d' ' -f1); do set -- "$@" --lora-scaled "$D/$f:0"; done; exec "$BIN" "$@" ) &
  PID=$!
  while kill -0 "$PID" 2>/dev/null; do
    sleep "$EVERY"
    if [ "$(sig)" != "$S" ]; then echo "llm-chat-entry: adapter set changed, restarting llama-server"; kill "$PID" 2>/dev/null; { wait "$PID"; } 2>/dev/null; break; fi
  done
  if kill -0 "$PID" 2>/dev/null; then :; else { wait "$PID"; } 2>/dev/null; RC=$?; [ "$(sig)" = "$S" ] && exit "$RC"; fi
  PID=""
done
