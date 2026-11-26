#!/usr/bin/env bash
# Runs every block of the course for each model, one after the other (fresh Nano store per model). PORT must serve this worktree's wasm/ (python3 -m http.server style preview).
cd "$(dirname "$0")"
for m in qwen2.5-1.5b qwen2.5-0.5b llama3.2-1b smollm2-360m; do
  PORT=${PORT:-8201} MODEL=$m PROF=/private/tmp/claude-501/-Users-sudhirganti-Applications-simulator-appliance-integF-packaging-tunnel/808d2878-fee3-409c-8be9-52dbc4c4b641/scratchpad/na/prof_c_$m OUT=../logs/course-$m.jsonl CLEAR=1 node courserun.mjs > ../logs/course-$m.log 2>&1
  echo "finished $m" >> ../logs/seq.log
done
