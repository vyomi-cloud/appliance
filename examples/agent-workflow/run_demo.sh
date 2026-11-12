#!/usr/bin/env bash
# Convenience wrapper: ./run_demo.sh [--run --runs 3 --only aws ...]. Assumes `ollama serve` is up with qwen2.5:3b + nomic-embed-text.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$(cd ../.. && pwd)"
exec "${PYTHON:-python3}" run_demo.py "$@"
