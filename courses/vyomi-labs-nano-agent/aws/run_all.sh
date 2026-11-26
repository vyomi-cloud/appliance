#!/usr/bin/env bash
# Runs each chapter's commands in order against your simulator. ./run_all.sh runs all; ./run_all.sh 3 5 runs only those.
# Chapters import each other's files, so they are first assembled side by side in .workspace/ (later chapters replace earlier versions of tools.py and agent.py).
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
rm -rf "$root/.workspace" && mkdir "$root/.workspace"
[ -f "$root/.env" ] && set -a && . "$root/.env" && set +a
want=" $* "
run_chapter() { n="$1"; shift; for d in "$root"/[0-9][0-9]-*/; do for f in "$d"*; do case "$f" in */README.md) ;; *) cp "$f" "$root/.workspace/";; esac; done; [ "$(basename "$d" | cut -c1-2)" = "$(printf %02d "$n")" ] && break; done; (cd "$root/.workspace" && "$@"); }
if [ "$want" = "  " ] || [[ "$want" == *" 1 "* ]]; then echo '== Chapter 1: The agent loop'; run_chapter 1 python loop.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 1 "* ]]; then echo '== Chapter 1: The agent loop'; run_chapter 1 python loop_limits.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Chapter 2: A model in your browser'; run_chapter 2 python protocol_test.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Chapter 2: A model in your browser'; run_chapter 2 python try_model.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Chapter 2: A model in your browser'; run_chapter 2 python measure_protocol.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Chapter 3: Tools'; run_chapter 3 python seed.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Chapter 3: Tools'; run_chapter 3 python try_tools.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Chapter 3: Tools'; run_chapter 3 python try_agent.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Chapter 4: Memory'; run_chapter 4 python try_memory.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Chapter 5: Knowledge (RAG)'; run_chapter 5 python build_index.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Chapter 5: Knowledge (RAG)'; run_chapter 5 python measure_retrieval.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Chapter 6: Guardrails'; run_chapter 6 python guard_test.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Chapter 6: Guardrails'; run_chapter 6 python try_guarded.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Chapter 7: Deploy and evaluate'; run_chapter 7 python bundle.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Chapter 7: Deploy and evaluate'; run_chapter 7 python deploy.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Chapter 7: Deploy and evaluate'; run_chapter 7 python evaluate.py; fi
