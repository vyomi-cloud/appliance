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
if [ "$want" = "  " ] || [[ "$want" == *" 1 "* ]]; then echo '== Layer 1: Models'; python fail_models.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 1 "* ]]; then echo '== Layer 1: Models'; python iam_models.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python deploy_runtime.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python invoke_agent.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python stop_session.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python runaway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python iam_runtime.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python tables.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python seed.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python deploy_tools.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python call_tools.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python tool_contract.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python iam_tools.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Design the RAG'; python show_design.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Pipeline'; python upload_docs.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Pipeline'; python vector_store.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Pipeline'; python knowledge_base.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Pipeline'; python ingest.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Pipeline'; python event_driven.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Pipeline'; python reingest.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Pipeline'; python dlq_ingest.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Knowledge Search (RAG)'; python search.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Knowledge Search (RAG)'; python rerank.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Knowledge Search (RAG)'; python deploy_kb_search.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Response Generation'; python guardrail.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Response Generation'; python output_guardrail.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Response Generation'; python grounded_answer.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Response Generation'; python retrieve_and_generate.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Response Generation'; python refusal.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Response Generation'; python poisoned_doc.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Memory'; python memory_create.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Memory'; python memory_events.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Memory'; python memory_recall.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Memory'; python memory_guard.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Agent Gateway'; python gateway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Agent Gateway'; python mcp_list.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Agent Gateway'; python mcp_call.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Agent Gateway'; python cedar_policy.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Agent Gateway'; python agent_via_gateway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Agent Gateway'; python cedar_enforce.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Actions and Approval'; python approver_inbox.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Actions and Approval'; python state_machine.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Actions and Approval'; python request_work_order.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Actions and Approval'; python approve.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Actions and Approval'; python reject.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Actions and Approval'; python history.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Actions and Approval'; python expiry.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Actions and Approval'; python risk_levels.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Actions and Approval'; python iam_approval.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Access and Perimeter'; python cognito_setup.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Access and Perimeter'; python waf.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Access and Perimeter'; python api_gateway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Access and Perimeter'; python call_with_token.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Access and Perimeter'; python call_without_token.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Access and Perimeter'; python token_attacks.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: Channels and Input Guardrails'; python input_guardrail.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: Channels and Input Guardrails'; python inbox_channel.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: Channels and Input Guardrails'; python guardrail_bypass.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: AgentOps and Observability'; python trace_agent.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: AgentOps and Observability'; python evaluators.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: AgentOps and Observability'; python cost_meter.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 14 "* ]]; then echo '== Layer 14: Governance and Security'; python kms_protect.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 14 "* ]]; then echo '== Layer 14: Governance and Security'; python trail.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 14 "* ]]; then echo '== Layer 14: Governance and Security'; python audit.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 14 "* ]]; then echo '== Layer 14: Governance and Security'; python key_rotation.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 14 "* ]]; then echo '== Layer 14: Governance and Security'; python audit_chain.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 14 "* ]]; then echo '== Layer 14: Governance and Security'; python audit_who.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 14 "* ]]; then echo '== Layer 14: Governance and Security'; python ship_it.py; fi
