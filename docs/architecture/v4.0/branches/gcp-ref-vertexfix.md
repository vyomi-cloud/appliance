# v4/gcp-ref-vertexfix: Vertex simulator gaps found by the GCP reference app

Lane 6 of round 2 of the GCP 13/13 build. Base: `origin/v4/gcp-ref-integ` 77b2a7fa6. Regression test: `tests/conformance/test_gcp_ref_vertexfix_sdk.py` (real Google SDKs, REST transports).

## Changes
- Model Armor (`core/gcp_agentgov_core.py`): templates accept proto integer enums (google-cloud-modelarmor sends `alt=json;enum-encoding=int`) and names; answers are in ints when the caller asked for ints. create/get/list/update/delete + sanitizeUserPrompt/sanitizeModelResponse proven with `ModelArmorClient`.
- Agent Engine (`core/gcp_agentengine_core.py`, `core/gcp_function_runtime.py`): the vertexai SDK sends `spec` in snake_case; it is stored and returned in canonical lowerCamelCase (class_methods stay as sent) so create/get/list/update/delete validate in the SDK. `spec.sourceCodeSpec.inlineSource` (tar.gz) is kept server-side. `:query` / `:streamQuery` run the entrypoint object from the source package in the existing function sandbox (`run_agent_engine`), with the Cloud Run env contract (GOOGLE_CLOUD_PROJECT, VYOMI_ENDPOINT, STORAGE_EMULATOR_HOST, metadata-server identity). `:streamQuery` is newline-delimited JSON for the google-genai/vertexai SDK (what its parser reads) and the HttpBody JSON array for gapic clients (existing behaviour).
- Sessions (`core/gcp_agentplatform_core.py`): `sessions/ID:appendEvent` plus ordered, timestamp-filterable events list with the SessionEvent shapes.
- Model catalogue (`core/gcp_vertex_core.py`): `publishers/google/models/<id>` for every served id including legacy gemini-* aliases; google publisher list includes all catalogue ids; Model fields (version, token limits, generation methods) added.
- generateContent / streamGenerateContent honour `modelArmorConfig` (`core/ai_models_core.py` calls `gcp_agentgov_core.armor_check`): MODEL_ARMOR block before the model; response template -> finishReason SAFETY.
- Capability JSON entries updated (model-armor, agent-engine, sessions, model-garden).

## Design decisions
- Source packages run through the lane-3 sandboxed subprocess runtime; no new backend. One process per call: set_up runs on every call and no instance state persists (sessions/memory hold state).
- Pickled objects (`create(agent=<object>)`, `spec.packageSpec`) are never unpickled; :query answers FAILED_PRECONDITION naming the supported form. The reference app uses source packages.
- The SDK tars a source directory under its relative path, so the archive root and each top-level directory are put on sys.path (module resolves as `app` or `dir.app`).

## Open issues
- requirements.txt is not pip-installed (pre-baked wheel set); missing packages surface as the agent's ImportError.
- Nano cannot spawn processes: source-packaged engines answer FAILED_PRECONDITION there.
- Token limits are the local models' 8192, not Gemini's real windows.
