"""Generates the per-block appendix for docs/labs/nano-matrix-{gcp,azure}.md.
Inputs: wasm/labs/data/<cloud>.json, evidence/nano-worker-run-as-written.json, evidence/labrun-reference-<cloud>.log.
Backend-readiness verdicts (BR) are hand-assigned from nano-replay-*.json + nano-chained-probe-*.json (see the docs); everything else is computed."""
import json, re, sys, os
EV = os.path.join(os.path.dirname(__file__), "..")
ROOT = os.path.join(EV, "..", "..", "..")
W = json.load(open(os.path.join(EV, "nano-worker-run-as-written.json")))

# BR codes: OK = every captured call is served by Nano; MODEL = needs a loaded model (503); SBX = needs function/agent execution Nano's sandbox cannot do;
# GRPC = Google gRPC transport (no REST variant in the block); AMQP = Service Bus AMQP over TCP; A:<what> = missing/incorrect Nano backend; NOHTTP = writes files only
GCP = {
 (1,"try_models.py"):("MODEL","chat+tool call: HTTP 503 'No in-browser model is loaded'; embedding served"),
 (2,"try_agent.py"):("MODEL","langgraph agent calls generateContent -> 503"),
 (2,"deploy_agent.py"):("OK","reasoningEngines create + LRO poll served"),
 (2,"query_agent.py"):("SBX","reasoningEngines:query -> 400 'needs the sandboxed subprocess runtime'"),
 (3,"seed.py"):("GRPC","Firestore client uses gRPC (FIRESTORE_EMULATOR_HOST); Nano serves Firestore REST only"),
 (3,"deploy_tools.py"):("OK","generateUploadUrl, PUT zip, CreateFunction -> ACTIVE served (bucket/project ids differ per space)"),
 (3,"call_asset_status.py"):("SBX","function URL answers 403; sandbox allows stdlib only, tool imports google.cloud.firestore"),
 (3,"check_write_tool.py"):("SBX","same as above, plus Firestore gRPC in the script itself"),
 (4,"upload_docs.py"):("OK","bucket create + object upload served (REST)"),
 (4,"create_kb.py"):("OK","RAG corpus, ragFiles:import, list served"),
 (4,"notify.py"):("A:project alias","notificationConfigs rejects topic 'projects/vyomi-project/...' (Nano project is nano-project); Pub/Sub via gRPC"),
 (4,"deploy_pipeline.py"):("SBX","functions deploy served; Eventarc trigger needs the function to run; ingest function imports google-cloud-storage"),
 (4,"test_pipeline.py"):("SBX","depends on the event-triggered ingest function executing"),
 (4,"replace_doc.py"):("SBX","depends on the ingest function; RAG import itself served"),
 (5,"search.py"):("OK","retrieveContexts served"),
 (5,"check_ranking.py"):("OK","retrieveContexts served"),
 (5,"deploy_kb_search.py"):("SBX","deploy served; function invocation not possible (imports google.cloud + google-auth)"),
 (6,"try_response.py"):("MODEL","retrieve served, generateContent 503"),
 (6,"screen_output.py"):("OK","Model Armor template + sanitize served"),
 (6,"safe_response.py"):("MODEL","generateContent 503"),
 (6,"grounded_generate.py"):("MODEL","generateContent 503"),
 (7,"memory.py"):("GRPC","Firestore client gRPC"),
 (7,"session_demo.py"):("MODEL","sessions + events served; the model turn 503"),
 (7,"remember.py"):("OK","memories create/get/retrieve served"),
 (7,"generate_memories.py"):("MODEL","memories:generate 503 (needs a model)"),
 (8,"register_tools.py"):("SBX","MCP tool server is a Cloud Run function; deploy served, execution not"),
 (8,"create_gateway.py"):("OK","agentGateways create/get/attachMcpServer served"),
 (8,"use_gateway.py"):("SBX","gateway /mcp forwards to the function above"),
 (8,"add_policy.py"):("OK","agentPolicies + Cedar test + attachPolicy served"),
 (9,"setup_inbox.py"):("GRPC","Pub/Sub publisher/subscriber clients use gRPC; REST topic/sub create works on Nano"),
 (9,"submit_request.py"):("MODEL","supervisor turn needs a model; Firestore + Pub/Sub gRPC"),
 (9,"approve_request.py"):("SBX","calls approval-decision and create-work-order functions; Pub/Sub + Firestore gRPC"),
 (9,"reject_request.py"):("SBX","same"),
 (10,"signin.py"):("A:Identity Toolkit","POST /v1/accounts:signUp -> 500 'ImportError: cannot import name app_context from core'"),
 (10,"service_account.py"):("A:project alias","SA create served; generateIdToken for agent-sa@vyomi-project -> 403 (the SA is agent-sa@nano-project)"),
 (10,"armor.py"):("OK","Cloud Armor policy create/get served (stored, not evaluated, as the chapter says)"),
 (10,"api_gateway.py"):("A:OpenAPI YAML","config create -> 400 'unexpected list item at line 12' (parser rejects PyYAML-style indentless lists)"),
 (10,"call_edge.py"):("A:API Gateway edge","depends on the config above; edge call returned 'No gateway serves this host'"),
 (11,"intake.py"):("OK","Model Armor served; Pub/Sub publish via gRPC client"),
 (11,"inbox_check.py"):("GRPC","Pub/Sub pull via gRPC"),
 (12,"export_trace.py"):("MODEL","agent run calls a model; Cloud Trace batchWrite served"),
 (12,"read_trace.py"):("OK","Trace read served"),
 (12,"log_run.py"):("OK","entries:write / entries:list served"),
 (12,"metric.py"):("OK","Monitoring timeSeries create served (REST)"),
 (12,"log_grpc.py"):("GRPC","explicitly the gRPC Logging path; Nano has no gRPC front"),
 (13,"create_key.py"):("OK","KMS key ring + key + rotation served"),
 (13,"seal_record.py"):("OK","KMS encrypt/decrypt with AAD, wrong AAD refused: served"),
 (13,"audit_trail.py"):("OK","admin-activity audit entries for CreateKeyRing/CreateCryptoKey/CreateTopic served"),
 (13,"ledger_audit.py"):("GRPC","Firestore gRPC"),
}
AZ = {
 (1,"create_openai.py"):("OK","account + model list + deployments served (models listed are the Nano set)"),
 (1,"try_models.py"):("MODEL","chat 503 ServiceUnavailable; embeddings served (all-minilm-l6-v2)"),
 (1,"try_more.py"):("MODEL","stream needs a model; dimensions + unknown deployment 404 served"),
 (2,"foundry_agents.py"):("OK","assistants/threads/messages/runs served (run output needs a model)"),
 (2,"try_graph.py"):("MODEL","local FastAPI app + langgraph + model; fastapi/uvicorn do not install in Pyodide"),
 (2,"deploy_container_app.py"):("OK","Container Apps ARM served"),
 (2,"call_container_app.py"):("SBX","needs a running container: BLOCKED even in the offline reference without a Docker runtime"),
 (3,"create_search.py"):("OK","Search service ARM + admin keys served"),
 (3,"seed.py"):("OK","Table storage (azure-data-tables wire) served"),
 (3,"deploy_tools.py"):("SBX","plan/site/settings/zipdeploy served; v1-layout zip is not parsed (functions list is empty)"),
 (3,"call_tools.py"):("SBX","'Entry point asset-status not found in function source'; sandbox has no azure.data.tables"),
 (4,"upload_docs.py"):("OK","Blob + storage ARM served"),
 (4,"kb_index.py"):("A:AI Search data plane","PUT /indexes(...) is not routed (falls to the S3 handler: NoSuchBucket)"),
 (4,"indexer.py"):("A:AI Search data plane","datasources/indexers/run not routed"),
 (4,"check_search.py"):("A:AI Search data plane","docs/search.post.search not routed"),
 (4,"deploy_ingest.py"):("SBX","Event Grid + function ARM served; the ingest function cannot execute"),
 (4,"new_doc.py"):("A:AI Search data plane","blob upload served; search not routed"),
 (5,"inspect_index.py"):("A:AI Search data plane","not routed"),
 (5,"embed_docs.py"):("A:AI Search data plane","not routed (vector fields)"),
 (5,"try_search.py"):("A:AI Search data plane","not routed"),
 (6,"try_respond.py"):("MODEL","search not routed + chat 503"),
 (6,"guard.py"):("A:AI Search data plane","Content Safety served; respond() path needs Search + model"),
 (6,"file_search.py"):("MODEL","assistants file_search tool needs a model"),
 (6,"on_your_data.py"):("A:AI Search data plane","On Your Data uses the Search index + a model"),
 (7,"short_term.py"):("MODEL","threads + a model turn"),
 (7,"try_memory.py"):("OK","Table-backed memory served"),
 (7,"no_managed_memory.py"):("OK","probes that managed-memory routes 404: served"),
 (8,"create_gateway.py"):("OK","APIM service, API, operations, policy, subscription served"),
 (8,"call_gateway.py"):("SBX","APIM gateway answers 502 BackendUnavailable: the backend is the function app"),
 (8,"policies.py"):("SBX","same backend dependency"),
 (8,"mcp_server.py"):("OK","APIM MCP server ARM served"),
 (9,"create_bus.py"):("OK","Service Bus ARM (namespace/topic/subscription) served"),
 (9,"park_request.py"):("AMQP","Table ledger OK; azure-servicebus sends over AMQP 1.0/TCP, not possible from a browser; functions (SBX)"),
 (9,"approve_request.py"):("AMQP","AMQP receive + functions"),
 (9,"reject_request.py"):("AMQP","AMQP + functions; ETag 412 on Table served"),
 (10,"entra.py"):("OK","Graph applications/addPassword/users served"),
 (10,"sign_in.py"):("OK","client-credentials token served; user password grant via the tenant token endpoint is the block's own workaround"),
 (10,"protect_gateway.py"):("SBX","APIM validate-jwt served; the gateway backend is a function"),
 (10,"waf.py"):("OK","Front Door WAF policy ARM served"),
 (11,"screen_input.py"):("OK","Content Safety text:analyze served"),
 (11,"content_filter.py"):("MODEL","RAI policy ARM served; the violent-prompt call needs a model"),
 (11,"inbox.py"):("AMQP","Service Bus AMQP receive"),
 (12,"create_observability.py"):("OK","Log Analytics workspace + App Insights component ARM served"),
 (12,"run_agent.py"):("MODEL","agent run: model + functions"),
 (12,"export_telemetry.py"):("A:App Insights ingestion","POST /v2.1/track -> 405"),
 (12,"query_telemetry.py"):("A:Log Analytics query","POST .../workspaces/<id>/query -> 405"),
 (12,"custom_table.py"):("A:Log Analytics query","data-collector + KQL query not served"),
 (12,"platform_metrics.py"):("OK","Monitor metrics ARM served"),
 (13,"create_vault.py"):("OK","vault ARM served"),
 (13,"make_key.py"):("A:Key Vault api-version routing","SDK sends api-version=2026-04-01 -> routed to App Configuration (404 'configuration store not found'); 7.5 works"),
 (13,"envelope.py"):("A:Key Vault api-version routing","same, for wrap/unwrap/encrypt"),
 (13,"audit.py"):("OK","Activity Log served"),
}
def main(cloud):
    d = json.load(open(os.path.join(ROOT, "wasm", "labs", "data", f"{cloud}.json")))
    BR = GCP if cloud == "gcp" else AZ
    wk = {(r["chapter"], r["file"]): r for r in W[cloud]}
    ref = open(os.path.join(EV, f"labrun-reference-{cloud}.log")).read()
    rows = ["| Ch | Block | Reference labrun | Nano as shipped | Same block in the Nano Pyodide worker | Nano backend if the SDK could run | Cause class | Detail |", "|---|---|---|---|---|---|---|---|"]
    cls = {"OK": "-", "MODEL": "(c) model", "SBX": "(b) function/agent sandbox", "GRPC": "(d) gRPC transport", "AMQP": "(d) AMQP transport"}
    for l in d["layers"]:
        for b in l["lab"]:
            if not b["run"]: continue
            w = wk.get((l["order"], b["file"]))
            m = re.search(r"No module named '([\w\.]+)'|The module '([\w\.\-]+)' is included in the Pyodide", w["text"]) if w else None
            mod = ((m.group(1) or m.group(2)) if m else "module/env")
            werr = ("FAIL: google SDK stack not in Pyodide (first miss: protobuf)" if mod == "protobuf" else "FAIL: missing " + mod) if w and not w["ok"] else "PASS"
            if w and not w["ok"] and "VYOMI_AZURE" in w["text"]: werr = "FAIL: env VYOMI_AZURE_* unset (and no azure-* SDK)"
            refres = "BLOCKED" if f"BLOCKED  {b['run']}" in ref else "PASS"
            code, det = BR[(l["order"], b["file"])]
            c = cls.get(code, "(a) missing/incorrect Nano backend: " + code.split(":", 1)[-1])
            rows.append(f"| {l['order']} | `{b['file']}` | {refres} | BLOCKED (Deploy needs a Mesh) | {werr} | {code.split(':')[0]} | {c} | {det} |")
    return "\n".join(rows)
if __name__ == "__main__":
    print(main(sys.argv[1]))
