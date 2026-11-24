#!/usr/bin/env bash
# Runs every chapter's commands in course order against your simulator.
set -euo pipefail
cd "$(dirname "$0")/app"
echo '== Chapter 1: Models'
python create_openai.py
echo '== Chapter 1: Models'
python try_models.py
echo '== Chapter 1: Models'
python try_more.py
echo '== Chapter 2: Agent Runtime'
python foundry_agents.py
echo '== Chapter 2: Agent Runtime'
python try_graph.py
echo '== Chapter 2: Agent Runtime'
python deploy_container_app.py
echo '== Chapter 2: Agent Runtime'
python call_container_app.py
echo '== Chapter 3: Tools'
python create_search.py
echo '== Chapter 3: Tools'
python seed.py
echo '== Chapter 3: Tools'
python deploy_tools.py
echo '== Chapter 3: Tools'
python call_tools.py
echo '== Chapter 4: Knowledge Pipeline'
python upload_docs.py
echo '== Chapter 4: Knowledge Pipeline'
python kb_index.py
echo '== Chapter 4: Knowledge Pipeline'
python indexer.py
echo '== Chapter 4: Knowledge Pipeline'
python check_search.py
echo '== Chapter 4: Knowledge Pipeline'
python deploy_ingest.py
echo '== Chapter 4: Knowledge Pipeline'
python new_doc.py
echo '== Chapter 5: Knowledge Search (RAG)'
python inspect_index.py
echo '== Chapter 5: Knowledge Search (RAG)'
python embed_docs.py
echo '== Chapter 5: Knowledge Search (RAG)'
python try_search.py
echo '== Chapter 6: Response Generation'
python try_respond.py
echo '== Chapter 6: Response Generation'
python guard.py
echo '== Chapter 6: Response Generation'
python file_search.py
echo '== Chapter 6: Response Generation'
python on_your_data.py
echo '== Chapter 7: Agent Memory'
python short_term.py
echo '== Chapter 7: Agent Memory'
python try_memory.py
echo '== Chapter 7: Agent Memory'
python no_managed_memory.py
echo '== Chapter 8: Agent Gateway'
python create_gateway.py
echo '== Chapter 8: Agent Gateway'
python call_gateway.py
echo '== Chapter 8: Agent Gateway'
python policies.py
echo '== Chapter 8: Agent Gateway'
python mcp_server.py
echo '== Chapter 9: Actions and Approval'
python create_bus.py
echo '== Chapter 9: Actions and Approval'
python park_request.py
echo '== Chapter 9: Actions and Approval'
python approve_request.py
echo '== Chapter 9: Actions and Approval'
python reject_request.py
echo '== Chapter 10: Access and Perimeter'
python entra.py
echo '== Chapter 10: Access and Perimeter'
python sign_in.py
echo '== Chapter 10: Access and Perimeter'
python protect_gateway.py
echo '== Chapter 10: Access and Perimeter'
python waf.py
echo '== Chapter 11: Channels and Input Guardrails'
python screen_input.py
echo '== Chapter 11: Channels and Input Guardrails'
python content_filter.py
echo '== Chapter 11: Channels and Input Guardrails'
python inbox.py
echo '== Chapter 12: AgentOps and Observability'
python create_observability.py
echo '== Chapter 12: AgentOps and Observability'
python run_agent.py
echo '== Chapter 12: AgentOps and Observability'
python export_telemetry.py
echo '== Chapter 12: AgentOps and Observability'
python query_telemetry.py
echo '== Chapter 12: AgentOps and Observability'
python custom_table.py
echo '== Chapter 12: AgentOps and Observability'
python platform_metrics.py
echo '== Chapter 13: Governance and Security'
python create_vault.py
echo '== Chapter 13: Governance and Security'
python make_key.py
echo '== Chapter 13: Governance and Security'
python envelope.py
echo '== Chapter 13: Governance and Security'
python audit.py
