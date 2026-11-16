#!/usr/bin/env bash
# Convenience wrapper: ./run_demo.sh [--run --runs 3 --only aws ...]. Assumes `ollama serve` is up with qwen3:4b-instruct-2507-q4_K_M + nomic-embed-text.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$(cd ../.. && pwd)"
exec "${PYTHON:-python3}" run_demo.py "$@"
