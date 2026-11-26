// node --test src/gcp/services/vertex-ai/studio/studio.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { retrievalOptions, applyPreset, lintDesign } from "../../../../common/ragstudio/engine.js";
import { toDocument, fromDocument, validate } from "../../../../common/ragstudio/document.js";
import { checkAdapter } from "../../../../common/ragstudio/adapter.js";
import { gcpDefaultDesign, designToApi, apiToDesign, toRagRetrievalConfig, traceRows, gcpLint, fileIdsFor, citationsFrom, retrieveBody } from "./gcpMap.js";
import { createFake } from "./fake.js";

test("design -> Vertex AI shapes and back", () => {
  const d = gcpDefaultDesign(), a = designToApi(d), f = a.transformation.ragFileChunkingConfig.fixedLengthChunking;
  assert.deepEqual(f, { chunkSize: 240, chunkOverlap: 48 });                       // 48 tokens x 5 chars, 20%
  assert.equal(a.importRagFilesConfig.gcsSource.uris[0], "gs://facilities-docs");
  assert.equal(a.ragEmbeddingModelConfig.vertexPredictionEndpoint.model, "publishers/google/models/text-embedding-005");
  const back = apiToDesign(a.transformation);
  assert.deepEqual(back.chunk, { strategy: "FIXED_SIZE", maxTokens: 48, overlapPct: 20 });
  assert.equal(designToApi(applyPreset(d, "policy-manuals")).notes.length, 1);   // SEMANTIC is applied as fixed-length
});
test("retrieval options -> ragRetrievalConfig (hybrid alpha, rerank pool, semantic)", () => {
  const d = gcpDefaultDesign(), o = retrievalOptions(d);
  assert.deepEqual(toRagRetrievalConfig(o), { topK: 4, hybridSearch: { alpha: 0.6 }, ranking: { rankService: { modelName: "semantic-ranker-default-004" } } });
  assert.deepEqual(toRagRetrievalConfig(retrievalOptions(applyPreset(d, "semantic-only"))), { topK: 8 });
  const body = retrieveBody({ name: "projects/p/locations/l/ragCorpora/1" }, "q", o, ["7"]);
  assert.deepEqual(body.vertexRagStore.ragResources, [{ ragCorpus: "projects/p/locations/l/ragCorpora/1", ragFileIds: ["7"] }]);
});
test("filter maps to ragFileIds and rejects unsupported keys", () => {
  const chunks = [{ id: "11-0", uri: "a.txt", metadata: { file: "a.txt" } }, { id: "22-0", uri: "b.txt", metadata: { file: "b.txt" } }, { id: "22-1", uri: "b.txt", metadata: { file: "b.txt" } }];
  assert.deepEqual(fileIdsFor({ key: "file", value: "b.txt" }, chunks), ["22"]);
  assert.equal(fileIdsFor(null, chunks), null);
  assert.throws(() => fileIdsFor({ key: "department", value: "hvac" }, chunks), /file only/);
});
test("generateContent groundingMetadata -> citations", () => {
  const gm = { groundingChunks: [{ retrievedContext: { uri: "projects/p/ragFiles/9", title: "boiler.txt", text: "Boiler inspection" } }, { retrievedContext: { uri: "gs://b/x.txt", title: "x.txt", text: "x" } }],
    groundingSupports: [{ segment: { text: "Inspected in October." }, groundingChunkIndices: [0, 1] }] };
  const c = citationsFrom(gm);
  assert.equal(c.length, 1);
  assert.deepEqual(c[0].retrievedReferences.map((r) => r.location.uri), ["boiler.txt", "gs://b/x.txt"]);
  assert.deepEqual(citationsFrom(null), []);
});
test("retrieve-trace candidates -> Studio trace rows", () => {
  const cm = new Map([["1-0", { uri: "a.txt", text: "alpha", tokens: 3, metadata: { file: "a.txt" } }]]);
  const tr = { candidates: [
    { chunkId: "1-0", uri: "x", vector_score: 0.9, vector_rank: 1, bm25_score: 2, bm25_rank: 1, fused_rank: 1, rerank_score: 0.8, returned: true, filtered_out_reason: null },
    { chunkId: "1-1", uri: "x", vector_score: 0.1, vector_rank: 9, bm25_score: 0, bm25_rank: null, fused_rank: 40, returned: false, filtered_out_reason: "below top-k" },
    { chunkId: "2-0", uri: "y", vector_score: null, returned: false, filtered_out_reason: "excluded by ragFileIds filter" }] };
  const rows = traceRows(tr, { numberOfResults: 12 }, cm, ["1-0"]);
  assert.deepEqual(rows.map((r) => r.id), ["1-0", "2-0"]);                      // rank 40 is outside the pool; filtered rows are kept
  assert.equal(rows[0].final_rank, 1); assert.equal(rows[0].text, "alpha"); assert.equal(rows[1].filtered_out_reason, "excluded by ragFileIds filter");
});
test("GCP lint: fixed-only chunking and filter keys", () => {
  const d = applyPreset(gcpDefaultDesign(), "policy-manuals");
  assert.ok(gcpLint(d).some((l) => l.id === "gcp-fixed-only"));
  d.retrieve.filterKey = "department";
  assert.ok(gcpLint(d).some((l) => l.id === "gcp-filter-key"));
  assert.ok(!lintDesign(gcpDefaultDesign()).some((l) => l.id === "embed-unknown"));   // text-embedding-005 is registered
});
test("gcp document export/import round-trips as cloud gcp", () => {
  const d = applyPreset(gcpDefaultDesign(), "maintenance-logs"), doc = toDocument(d, "gcp");
  assert.equal(doc.cloud, "gcp"); assert.deepEqual(validate(JSON.parse(JSON.stringify(doc))), []);
  assert.equal(fromDocument(doc).design.embed.model, "text-embedding-005");
});
test("GCP fake conforms to the adapter and answers with gs:// citations", async () => {
  const f = createFake();
  assert.deepEqual(checkAdapter(f), []);
  const o = retrievalOptions(gcpDefaultDesign());
  const r = await f.retrieve("How often must HVAC filters be replaced?", o);
  assert.ok(r.contexts.contexts.length > 0 && r.contexts.contexts[0].sourceUri.startsWith("gs://"));
  const a = await f.rag("How often must HVAC filters be replaced?", o);
  assert.ok(/90 days/.test(a.output.text) && a.citations[0].retrievedReferences[0].location.uri.startsWith("gs://"));
  assert.equal((await f.rag("What is the CEO's favourite colour?", o)).grounded, false);
  await f.applyDesign(designToApi({ ...gcpDefaultDesign(), chunk: { strategy: "FIXED_SIZE", maxTokens: 20, overlapPct: 10 } }));
  const before = (await f.chunks()).chunks.length; await f.ingest();
  assert.ok((await f.chunks()).chunks.length > before);
});
