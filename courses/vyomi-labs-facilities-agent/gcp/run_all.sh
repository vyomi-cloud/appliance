#!/usr/bin/env bash
# Runs the layers' commands in course order against your simulator. ./run_all.sh runs every layer; ./run_all.sh 3 7 runs only those.
# Layers import each other's files, so the files are first assembled side by side in .workspace/ (the same flat layout the course deploys from).
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
rm -rf "$root/.workspace" && mkdir "$root/.workspace"
for d in "$root"/[0-9][0-9]-*/; do for f in "$d"*; do case "$f" in */README.md) ;; *) cp "$f" "$root/.workspace/";; esac; done; done
[ -f "$root/.env" ] && set -a && . "$root/.env" && set +a
cd "$root/.workspace"
want=" $* "
if [ "$want" = "  " ] || [[ "$want" == *" 1 "* ]]; then echo '== Layer 1: Models'; python try_models.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python try_agent.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python deploy_agent.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python query_agent.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python seed.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python deploy_tools.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python call_asset_status.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python check_write_tool.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python upload_docs.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python create_kb.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python notify.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python deploy_pipeline.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python test_pipeline.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python replace_doc.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Search (RAG)'; python search.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Search (RAG)'; python check_ranking.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Search (RAG)'; python deploy_kb_search.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Response Generation'; python try_response.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Response Generation'; python screen_output.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Response Generation'; python safe_response.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Response Generation'; python grounded_generate.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Agent Memory'; python memory.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Agent Memory'; python session_demo.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Agent Memory'; python remember.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Agent Memory'; python generate_memories.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Gateway'; python register_tools.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Gateway'; python create_gateway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Gateway'; python use_gateway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Gateway'; python add_policy.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Actions and Approval'; python setup_inbox.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Actions and Approval'; python submit_request.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Actions and Approval'; python approve_request.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Actions and Approval'; python reject_request.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Access and Perimeter'; python signin.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Access and Perimeter'; python service_account.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Access and Perimeter'; python armor.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Access and Perimeter'; python api_gateway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Access and Perimeter'; python call_edge.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Channels and Input Guardrails'; python intake.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Channels and Input Guardrails'; python inbox_check.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python export_trace.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python read_trace.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python log_run.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python metric.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python log_grpc.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: Governance and Security'; python create_key.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: Governance and Security'; python seal_record.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: Governance and Security'; python audit_trail.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: Governance and Security'; python ledger_audit.py; fi
