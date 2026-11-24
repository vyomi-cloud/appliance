#!/usr/bin/env bash
# Runs every chapter's commands in course order against your simulator.
set -euo pipefail
cd "$(dirname "$0")/app"
echo '== Chapter 1: Models'
python try_models.py
echo '== Chapter 2: Agent Runtime'
python deploy_runtime.py
echo '== Chapter 2: Agent Runtime'
python invoke_agent.py
echo '== Chapter 2: Agent Runtime'
python stop_session.py
echo '== Chapter 3: Tools'
python tables.py
echo '== Chapter 3: Tools'
python seed.py
echo '== Chapter 3: Tools'
python deploy_tools.py
echo '== Chapter 3: Tools'
python call_tools.py
echo '== Chapter 4: Knowledge Pipeline'
python upload_docs.py
echo '== Chapter 4: Knowledge Pipeline'
python vector_store.py
echo '== Chapter 4: Knowledge Pipeline'
python knowledge_base.py
echo '== Chapter 4: Knowledge Pipeline'
python ingest.py
echo '== Chapter 4: Knowledge Pipeline'
python event_driven.py
echo '== Chapter 5: Knowledge Search (RAG)'
python search.py
echo '== Chapter 5: Knowledge Search (RAG)'
python rerank.py
echo '== Chapter 5: Knowledge Search (RAG)'
python deploy_kb_search.py
echo '== Chapter 6: Response Generation'
python guardrail.py
echo '== Chapter 6: Response Generation'
python output_guardrail.py
echo '== Chapter 6: Response Generation'
python grounded_answer.py
echo '== Chapter 6: Response Generation'
python retrieve_and_generate.py
echo '== Chapter 7: Agent Memory'
python memory_create.py
echo '== Chapter 7: Agent Memory'
python memory_events.py
echo '== Chapter 7: Agent Memory'
python memory_recall.py
echo '== Chapter 8: Agent Gateway'
python gateway.py
echo '== Chapter 8: Agent Gateway'
python mcp_list.py
echo '== Chapter 8: Agent Gateway'
python mcp_call.py
echo '== Chapter 8: Agent Gateway'
python cedar_policy.py
echo '== Chapter 8: Agent Gateway'
python agent_via_gateway.py
echo '== Chapter 9: Actions and Approval'
python approver_inbox.py
echo '== Chapter 9: Actions and Approval'
python state_machine.py
echo '== Chapter 9: Actions and Approval'
python request_work_order.py
echo '== Chapter 9: Actions and Approval'
python approve.py
echo '== Chapter 9: Actions and Approval'
python reject.py
echo '== Chapter 9: Actions and Approval'
python history.py
echo '== Chapter 10: Access and Perimeter'
python cognito_setup.py
echo '== Chapter 10: Access and Perimeter'
python waf.py
echo '== Chapter 10: Access and Perimeter'
python api_gateway.py
echo '== Chapter 10: Access and Perimeter'
python call_with_token.py
echo '== Chapter 10: Access and Perimeter'
python call_without_token.py
echo '== Chapter 11: Channels and Input Guardrails'
python input_guardrail.py
echo '== Chapter 11: Channels and Input Guardrails'
python inbox_channel.py
echo '== Chapter 12: AgentOps and Observability'
python trace_agent.py
echo '== Chapter 12: AgentOps and Observability'
python evaluators.py
echo '== Chapter 13: Governance and Security'
python kms_protect.py
echo '== Chapter 13: Governance and Security'
python trail.py
echo '== Chapter 13: Governance and Security'
python audit.py
