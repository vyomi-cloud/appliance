# v4/gcp-ref-corefix: GCP reference-architecture core fixes

Lane 2 of the GCP 13/13 reference-architecture build. Fixes the small simulator gaps found by the GCP probe
(`docs/architecture/v4.0/REF-ARCH-PROBE-GCP.md`), each proven with the real Google client libraries in
`tests/conformance/test_gcp_ref_corefix_sdk.py` (one in-process simulator, REST transports, endpoint changed only).

## Changes

| # | Gap | Fix | SDK call that now passes |
|---|---|---|---|
| 1 | Logging `timestamp>=` returned nothing | `core/gcp_logging_core.py`: `timestamp`/`receiveTimestamp` comparisons (`>= <= > < = !=`) compare RFC 3339 instants (any offset, fraction, `Z`) instead of strings | `logging.Client(_use_grpc=False).list_entries(filter_=..., order_by=ASCENDING/DESCENDING)`, incl. the no-filter default the SDK decorates with a timestamp |
| 2 | Trace v1 read of v2 spans broke | `core/gcp_trace_core.py`: one store already; v1 now returns decimal uint64 `spanId`/`parentSpanId` (v2 stays 16-hex). Also accepts the integer enums (`view`, `spanKind`) the SDK's REST transport sends | `trace_v1.TraceServiceClient.get_trace / list_traces(COMPLETE)` after `trace_v2.batch_write_spans` |
| 3 | KMS ignored AAD | `core/gcp_kms_core.py`: AAD sha256 bound into the authenticated plaintext on encrypt, checked on decrypt (wrong/missing/unexpected AAD = 400 INVALID_ARGUMENT); `additionalAuthenticatedDataCrc32c` verified; old ciphertexts decrypt as before | `kms.decrypt(additional_authenticated_data=...)` |
| 4 | Event function failed on `print` | `core/gcp_run_core.py`: the minimal function sandbox gets a capturing `print`; output goes to Cloud Logging (`run.googleapis.com/stdout`, also for the import path). The CloudEvent is a dict that also supports `event.data` / `event.type` | Eventarc storage trigger -> function using `print(event.data...)`; delivery status delivered, text read back with `list_entries` |
| 5 | No GCS `notificationConfigs` | `core/gcp_storage_core.py`: insert/list/get/delete; object finalize/delete publish into the shared Pub/Sub core via a router hook (`core/aws_wire_router.py`), honouring `event_types`, `object_name_prefix`, `custom_attributes`, `payload_format`; missing topic = 400 | `bucket.notification(...).create()/exists()/list_notifications()/delete()` + `subscriber.pull` |
| 6 | `generateContent` with a RAG retrieval tool was 400 | `core/ai_models_core.py`: `tools[].retrieval.vertexRagStore` (snake or camel case) runs `gcp_agentplatform_core._retrieve` first, injects chunks into the system instruction, returns `groundingMetadata` (groundingChunks, groundingSupports, retrievalQueries). No local model = the standard 503; unknown corpus = 404 | `google.genai` `Tool(retrieval=Retrieval(vertex_rag_store=...))`; model-free proof: 503 not 400, retrieval and grounding checked with a stub backend |

Capability registry (`core/capabilities/gcp/`): logs.explorer, kms.crypto.symmetric, monitoring.trace-explorer, eventarc.triggers,
vertex-ai.gemini, vertex-ai.rag-engine updated; new `gcp.storage.notifications` (limited). Levels unchanged except the new entry.

## Design decisions

- No new backend and no new engine: every fix is a few lines inside an existing core (the Pub/Sub publish reuses `gcp_pubsub_core._publish`).
  Lane 4 swaps Pub/Sub for a real emulator; the storage core only calls `store.publish_hook` / `store.topic_exists` (router-linked), so that swap does not touch this code.
- AAD is bound by sealing the plaintext (same trick `core/kms_core.py` uses for AWS EncryptionContext) rather than changing the engine, so it also works with the Vault Transit engine.
- Grounding supports are a deterministic lexical match (word overlap per answer sentence, UTF-8 byte offsets); no extra model call.
- Contract for the app lane: function logs are in Cloud Logging under `logName=projects/P/logs/run.googleapis.com%2Fstdout` (filter text `stdout`); notification topic must exist before `notification.create()`.

## Open issues

- `streamGenerateContent` with a retrieval tool runs the retrieval but does not attach groundingMetadata.
- `OBJECT_ARCHIVE` / `OBJECT_METADATA_UPDATE` accepted in `event_types` but never emitted; Pub/Sub publisher-permission check not modelled.
- Logging still has no OR/parentheses in the filter language; the Python Logging/Monitoring gapic clients stay gRPC-only (lane 4).
- Verified on host CPython (capability sweep subset `CAP_ONLY=...` 7/7 on the nano substrate, relay cores parity); not run in a real browser/Pyodide.
- The SDK test needs the google libs in the capability venv (added to `CAPABILITY-CHECK-ENV.md`).
