# GCP lab gaps (blocks left out because the simulator, not the lab, is wrong)

## Chapter 6: Vertex AI Search (Discovery Engine) data store

Tried: `discoveryengine_v1.DataStoreServiceClient.create_data_store(...).result()`, then `DocumentServiceClient.import_documents(...)` and
`SearchServiceClient.search(...)` over the boiler SOP (REST transport, `api_endpoint` pointed at the simulator), as a standalone script.

Error: `google.protobuf.json_format.ParseError: Failed to parse metadata field: Can not find message descriptor by type_url:
type.googleapis.com/google.cloud.aiplatform.v1.GenericOperationMetadata at Operation.metadata.`

Cause: the simulator answers the Discovery Engine long-running operation with an `aiplatform.v1` metadata type URL instead of a
`discoveryengine.v1` one, so the client cannot decode the operation unless `google.cloud.aiplatform_v1` happens to be imported in the same process
(then the whole sequence passes: verified, 1 search result). Importing aiplatform_v1 just to dodge this would hide a real simulator bug from the
learner, so the block is not published. Fix on the simulator side: emit `google.cloud.discoveryengine.v1.CreateDataStoreMetadata` /
`ImportDocumentsMetadata` as the operation metadata type. The reference app only passes this step because it imports aiplatform_v1 earlier.

## Not gaps, but stated limits (in the chapter text)

- Chapter 1: Cloud Armor rules are stored, not evaluated by the simulator.
- Chapter 5: Google Cloud has no managed approval-workflow service; the approval is assembled from Pub/Sub + Cloud Run functions + a Firestore ledger.
- Chapter 4: no Google client library exists for Agent Platform gateways / MCP servers / agent policies; REST through AuthorizedSession.
- Chapters 3, 9, 10, 11 model replies come from the deterministic test stub (tools/llm_stub), not a real model.
- Chapter 6 retrieval scores come from the simulator's lexical vectors when no embedding model is reachable.
