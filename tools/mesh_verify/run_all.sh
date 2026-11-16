#!/bin/sh
# Order matters: the single llama-server slot serialises requests, so run one script at a time.  PY needs boto3+fastapi+uvicorn.
PY=${PY:-python3}; cd "$(dirname "$0")/../.."
for s in agent_tools guardrail_eval judge_eval kb_quality; do echo "=== $s"; PYTHONPATH=. $PY tools/mesh_verify/$s.py; done
