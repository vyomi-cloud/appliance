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
if [ "$want" = "  " ] || [[ "$want" == *" 1 "* ]]; then echo '== Layer 1: Models'; python create_openai.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 1 "* ]]; then echo '== Layer 1: Models'; python try_models.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 1 "* ]]; then echo '== Layer 1: Models'; python try_more.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python foundry_agents.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python try_graph.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python deploy_container_app.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 2 "* ]]; then echo '== Layer 2: Agent Runtime'; python call_container_app.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python create_search.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python seed.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python deploy_tools.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 3 "* ]]; then echo '== Layer 3: Tools'; python call_tools.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python upload_docs.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python kb_index.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python indexer.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python check_search.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python deploy_ingest.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 4 "* ]]; then echo '== Layer 4: Knowledge Pipeline'; python new_doc.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Search (RAG)'; python inspect_index.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Search (RAG)'; python embed_docs.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 5 "* ]]; then echo '== Layer 5: Knowledge Search (RAG)'; python try_search.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Response Generation'; python try_respond.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Response Generation'; python guard.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Response Generation'; python file_search.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 6 "* ]]; then echo '== Layer 6: Response Generation'; python on_your_data.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Agent Memory'; python short_term.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Agent Memory'; python try_memory.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 7 "* ]]; then echo '== Layer 7: Agent Memory'; python no_managed_memory.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Gateway'; python create_gateway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Gateway'; python call_gateway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Gateway'; python policies.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 8 "* ]]; then echo '== Layer 8: Agent Gateway'; python mcp_server.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Actions and Approval'; python create_bus.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Actions and Approval'; python park_request.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Actions and Approval'; python approve_request.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 9 "* ]]; then echo '== Layer 9: Actions and Approval'; python reject_request.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Access and Perimeter'; python entra.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Access and Perimeter'; python sign_in.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Access and Perimeter'; python protect_gateway.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 10 "* ]]; then echo '== Layer 10: Access and Perimeter'; python waf.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Channels and Input Guardrails'; python screen_input.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Channels and Input Guardrails'; python content_filter.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 11 "* ]]; then echo '== Layer 11: Channels and Input Guardrails'; python inbox.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python create_observability.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python run_agent.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python export_telemetry.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python query_telemetry.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python custom_table.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 12 "* ]]; then echo '== Layer 12: AgentOps and Observability'; python platform_metrics.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: Governance and Security'; python create_vault.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: Governance and Security'; python make_key.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: Governance and Security'; python envelope.py; fi
if [ "$want" = "  " ] || [[ "$want" == *" 13 "* ]]; then echo '== Layer 13: Governance and Security'; python audit.py; fi
