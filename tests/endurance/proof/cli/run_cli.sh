#!/bin/sh
# CLI (aws cli) proof: run_cli.sh <endpoint> <tfstate> <out.json>
exec "${PYTHON:-$HOME/.vyomi-endurance/venv/bin/python}" "$(dirname "$0")/../run_checks.py" cli "$@"
