#!/usr/bin/env bash
# Runs every chapter's commands in course order against your simulator.
set -euo pipefail
cd "$(dirname "$0")/app"
echo '== Chapter 1: Models'
python try_models.py
echo '== Chapter 2: Agent Runtime'
python try_agent.py
echo '== Chapter 2: Agent Runtime'
python deploy_agent.py
echo '== Chapter 2: Agent Runtime'
python query_agent.py
echo '== Chapter 3: Tools'
python seed.py
echo '== Chapter 3: Tools'
python deploy_tools.py
echo '== Chapter 3: Tools'
python call_asset_status.py
echo '== Chapter 3: Tools'
python check_write_tool.py
echo '== Chapter 4: Knowledge Pipeline'
python upload_docs.py
echo '== Chapter 4: Knowledge Pipeline'
python create_kb.py
echo '== Chapter 4: Knowledge Pipeline'
python notify.py
echo '== Chapter 4: Knowledge Pipeline'
python deploy_pipeline.py
echo '== Chapter 4: Knowledge Pipeline'
python test_pipeline.py
echo '== Chapter 4: Knowledge Pipeline'
python replace_doc.py
echo '== Chapter 5: Knowledge Search (RAG)'
python search.py
echo '== Chapter 5: Knowledge Search (RAG)'
python check_ranking.py
echo '== Chapter 5: Knowledge Search (RAG)'
python deploy_kb_search.py
echo '== Chapter 6: Response Generation'
python try_response.py
echo '== Chapter 6: Response Generation'
python screen_output.py
echo '== Chapter 6: Response Generation'
python safe_response.py
echo '== Chapter 6: Response Generation'
python grounded_generate.py
echo '== Chapter 7: Agent Memory'
python memory.py
echo '== Chapter 7: Agent Memory'
python session_demo.py
echo '== Chapter 7: Agent Memory'
python remember.py
echo '== Chapter 7: Agent Memory'
python generate_memories.py
echo '== Chapter 8: Agent Gateway'
python register_tools.py
echo '== Chapter 8: Agent Gateway'
python create_gateway.py
echo '== Chapter 8: Agent Gateway'
python use_gateway.py
echo '== Chapter 8: Agent Gateway'
python add_policy.py
echo '== Chapter 9: Actions and Approval'
python setup_inbox.py
echo '== Chapter 9: Actions and Approval'
python submit_request.py
echo '== Chapter 9: Actions and Approval'
python approve_request.py
echo '== Chapter 9: Actions and Approval'
python reject_request.py
echo '== Chapter 10: Access and Perimeter'
python signin.py
echo '== Chapter 10: Access and Perimeter'
python service_account.py
echo '== Chapter 10: Access and Perimeter'
python armor.py
echo '== Chapter 10: Access and Perimeter'
python api_gateway.py
echo '== Chapter 10: Access and Perimeter'
python call_edge.py
echo '== Chapter 11: Channels and Input Guardrails'
python intake.py
echo '== Chapter 11: Channels and Input Guardrails'
python inbox_check.py
echo '== Chapter 12: AgentOps and Observability'
python export_trace.py
echo '== Chapter 12: AgentOps and Observability'
python read_trace.py
echo '== Chapter 12: AgentOps and Observability'
python log_run.py
echo '== Chapter 12: AgentOps and Observability'
python metric.py
echo '== Chapter 12: AgentOps and Observability'
python log_grpc.py
echo '== Chapter 13: Governance and Security'
python create_key.py
echo '== Chapter 13: Governance and Security'
python seal_record.py
echo '== Chapter 13: Governance and Security'
python audit_trail.py
echo '== Chapter 13: Governance and Security'
python ledger_audit.py
