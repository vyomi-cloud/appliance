#!/bin/sh
# SDK (boto3) proof: run_sdk.py <endpoint> <tfstate> <out.json>
exec "${PYTHON:-$HOME/.vyomi-endurance/venv/bin/python}" "$(dirname "$0")/../run_checks.py" sdk "$@"
