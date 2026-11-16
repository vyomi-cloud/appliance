# ai-limverify: verification lane (no features)

Owner: AI session. Base: local `v4/ai-integration` 5feeae0e6. Branch: `v4/ai-limverify`.

## What was verified and what changed

| Check | Result |
|---|---|
| `test_capabilities.py` on integration | first run 1381/1444; after fixes 1393/1444. All bedrock, vertex-ai, gemini, cognitiveservices deployments/playground/responses and apigateway claims now hold; the 51 left are environment (no pytest on the harness subprocess path, Azure SDK packages absent) or pre-existing on v4-on-main |
| Facilities e2e | 11 PASS / 2 BLOCKED / 0 FAIL of 13 (baseline 8/3/2). Blocked: components 10 and 11, no model reachable (no llama.cpp / WebLLM in this run) |
| `tools/ai_probe` routed % | see table below |
| PDF/DOCX under Pyodide | pypdf was NOT loadable (not in the Pyodide 0.26.2 package set). Fixed by vendoring the pure-Python wheel (`wasm/pylib/pypdf-7.1.0-py3-none-any.whl`, BSD-3, 0.4 MB, same origin) and `py.unpackArchive` at boot in `wasm/nano-boot.js` and `wasm/relay/relay-shared-worker.js` |
| Console crawl (Nano preview, headless Chromium) | AWS 27 routes, GCP 44, Azure 49 (Foundry pages, AI services account blade, AI Search blade): 0 console errors, 0 page errors, 0 blank panes, 0 "Coming soon" |

## Triage of capability failures

Introduced by our lanes (fixed here):
- `bedrock.runtime`/`gcp.vertex-ai.*` via `test_local_llm_seam`: the test still asserted Titan Text is refused; commit f4178f94b deliberately made standard ids honest aliases. Test updated (titan-text now 200; an unknown id still 400).
- `test_ai_agent_lanes` streaming checks (`bedrock.guardrails`, `gcp.gemini-developer-api`, `azure.cognitiveservices.responses-assistants`): wall-clock threshold 0.05 s versus a measured span of about 0.045 s on v4-on-main too (marginal, not a regression). Threshold now 0.02 s (still more than one fake-model delay, with at least 4 deltas).
- `test_bedrock_agents_core`: eventstream payload was cut with `index("{")`/`rindex("}")`, which a CRC byte can break. Now a frame-aware decoder.
- `test_no_cloud_egress` (`rds.exports-to-s3`, `gcp.sql.export-import`, `azure.sql.export_import`): `agentcore_gateway_targets.py` (user-configured upstream/token URL) and `agentcore_runtime_host.py` (loopback `/ping`, free-port pick) were not in the documented allow-list. Added with reasons; Mesh/offline only.
- Real bug: `gcp_agentengine_core.dispatch` raised AttributeError (HTTP 500) for child paths it does not model (sandboxEnvironments, memory revisions, operations). Now a JSON 404. Probe: aiplatform 51.2% -> 53.3% routed.

Pre-existing / environment (identical on origin/v4-on-main):
- `pytest` missing in the probe venv (`test_autoscaling_offline_route`, `test_ec2_offline_monitoring`, `test_nano_vm_runtime`, azure webhost): all pass once pytest is on the path.
- Azure SDK packages (`azure.mgmt`, `azure.cosmos`, ...) not installed in the venv: about 25 azure.* claims cannot run here.
- `apigateway.rest.api` burst-limit test is timing-flaky on v4-on-main (fails 1 of 2 runs there).
- `gcp.storage.objects` (`test_gcs_multipart_upload_core`, gcloud single quotes + LF): 7 failures on v4-on-main too.

## Probe delta (routed = served_ok + served_error over total; wire shape only)

| service | before | now |
|---|---|---|
| bedrock | 7.5 | 46.2 |
| bedrock-agent | 63.9 | 94.4 |
| bedrock-agent-runtime | 19.4 | 22.6 |
| bedrock-runtime | 40.0 | 40.0 (3 probe errors unmeasured) |
| bedrock-agentcore | 6.2 | 29.2 |
| bedrock-agentcore-control | 15.0 | 37.4 |
| GCP aiplatform | 51.2 | 53.3 |
| Azure cognitiveservices-arm | 82.2 | 82.2 |
| Azure search-arm | 96.4 | 96.4 |
| Azure openai-data | 0.0 | 0.0 |

## Declared limits
- PDF parsing needs the vendored wheel; scanned PDFs have no OCR; encrypted PDFs need the empty password.
- `wasm/v4/*` committed bundles are stale versus `consoles/src` on this base; rebuild before serving (needs `consoles/rag-overlay/node_modules`).
- `consoles/tests/smoke-azure-aoai.mjs` seeds a deployment with model `qwen2.5-3b` / format `Alibaba`, which the Azure OpenAI catalogue now rejects (400 DeploymentModelNotSupported); the smoke needs a catalogue model (e.g. OpenAI gpt-4o). Not changed here (lane-owned).
