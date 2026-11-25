// node --test src/azure/services/aisearch/studio/studio.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { applyPreset, defaultDesign, lintDesign, retrievalOptions, scoreRow, aggregate, DEFAULT_GOLDEN } from "../../../../common/ragstudio/engine.js";
import { toDocument, fromDocument, validate } from "../../../../common/ragstudio/document.js";
import { checkAdapter } from "../../../../common/ragstudio/adapter.js";
import { NAMES, azureToChunk, chatBody, defaultAzureDesign, designToAzure, modeOf, queryBody } from "./azureMap.js";
import { createFake } from "./fake.js";
globalThis.document ??= { querySelector: () => null };   // common/wire.js reads a <meta> at import
globalThis.window ??= globalThis; globalThis.location = { origin: "http://localhost", pathname: "/v4/azure/", search: "", hash: "" };
const { traceRows } = await import("./backend.js");

test("chunking maps to SplitSkill pages and back", () => {
  const d = defaultAzureDesign(); d.chunk = { strategy: "FIXED_SIZE", maxTokens: 200, overlapPct: 10 };
  const s = designToAzure(d).skillset.skills[0];
  assert.equal(s["@odata.type"], "#Microsoft.Skills.Text.SplitSkill"); assert.equal(s.textSplitMode, "pages");
  assert.equal(s.maximumPageLength, 800); assert.equal(s.pageOverlapLength, 80);
  assert.deepEqual(azureToChunk({ skills: [s] }), { strategy: "FIXED_SIZE", maxTokens: 200, overlapPct: 10 });
});
test("tiny chunk sizes clamp to the engine minimum page length (300)", () => {
  const d = defaultAzureDesign(); d.chunk.maxTokens = 20;
  assert.equal(designToAzure(d).skillset.skills[0].maximumPageLength, 300);
});
test("semantic and hierarchical strategies are flagged as approximated; NONE = whole documents", () => {
  const d = defaultAzureDesign(); d.chunk.strategy = "SEMANTIC";
  assert.ok(designToAzure(d).notes[0].includes("approximated"));
  d.chunk.strategy = "NONE"; const sk = designToAzure(d).skillset; assert.equal(azureToChunk(sk).strategy, "NONE");
});
test("embedding -> AzureOpenAIEmbeddingSkill + vector dimensions + profile", () => {
  const d = defaultAzureDesign(); d.embed.model = "text-embedding-3-large";
  const m = designToAzure(d, { aoai: { account: "aoai1", embedDeployment: "emb" } });
  const e = m.skillset.skills[1];
  assert.equal(e["@odata.type"], "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill"); assert.equal(e.dimensions, 3072); assert.equal(e.deploymentId, "emb"); assert.equal(e.resourceUri, "https://aoai1.openai.azure.com");
  const vf = m.index.fields.find((f) => f.name === "text_vector"); assert.equal(vf.dimensions, 3072); assert.equal(vf.vectorSearchProfile, NAMES.profile);
  assert.equal(m.skillset.indexProjections.selectors[0].targetIndexName, NAMES.index);
});
test("retrieve.searchType + rerank -> docs/search mode", () => {
  const o = (patch, rr = false) => retrievalOptions({ ...defaultAzureDesign(), retrieve: { searchType: "HYBRID", topK: 8, hybridWeight: 0.5, filterKey: "", filterValue: "", ...patch }, rerank: { enabled: rr, topN: 3 } });
  assert.equal(modeOf(o({ hybridWeight: 0 })), "text"); assert.equal(modeOf(o({})), "hybrid"); assert.equal(modeOf(o({ searchType: "SEMANTIC" })), "vector");
  let b = queryBody("q", o({})); assert.equal(b.search, "q"); assert.equal(b.vectorQueries[0].kind, "text"); assert.equal(b.vectorQueries[0].weight, 1); assert.equal(b.queryType, undefined);
  b = queryBody("q", o({ hybridWeight: 0 })); assert.equal(b.vectorQueries, undefined);
  b = queryBody("q", o({ searchType: "SEMANTIC" })); assert.equal(b.search, "*"); assert.equal(b.vectorQueries.length, 1);
  b = queryBody("q", o({}, true)); assert.equal(b.queryType, "semantic"); assert.equal(b.semanticConfiguration, NAMES.semantic);
  b = queryBody("q", o({ filterKey: "title", filterValue: "a'b" })); assert.equal(b.filter, "title eq 'a''b'");
});
test("chat on your data body", () => {
  const o = retrievalOptions({ ...defaultAzureDesign() });
  const b = chatBody("q", o, { endpoint: "https://s.search.windows.net/", key: "K", threshold: 0.3 }), p = b.data_sources[0].parameters;
  assert.equal(b.data_sources[0].type, "azure_search"); assert.equal(p.index_name, NAMES.index); assert.equal(p.authentication.key, "K"); assert.equal(p.query_type, "vector_semantic_hybrid"); assert.equal(p.top_n_documents, 4); assert.equal(p.semantic_configuration, NAMES.semantic);
});
test("document export/import round-trips with cloud=azure", () => {
  const d = applyPreset(defaultAzureDesign(), "policy-manuals");
  const doc = toDocument(d, "azure", { embeddingDimensions: designToAzure(d).dims });
  assert.deepEqual(validate(doc), []); assert.equal(doc.cloud, "azure"); assert.equal(doc.embedding.dimensions, 1536);
  const back = fromDocument(JSON.parse(JSON.stringify(doc)));
  assert.deepEqual(back.design.chunk, d.chunk); assert.equal(back.design.embed.model, "text-embedding-3-small"); assert.deepEqual(back.design.retrieve, d.retrieve);
});
test("lint knows the Azure embedding models", () => {
  const d = defaultAzureDesign(); assert.ok(!lintDesign(d).some((l) => l.id === "embed-unknown"));
  d.chunk.maxTokens = 9000; assert.ok(lintDesign(d).some((l) => l.id === "chunk-over-window"));
});
test("fake adapter conforms, applyDesign re-chunks through the Azure skillset, rag cites", async () => {
  const f = createFake(); assert.deepEqual(checkAdapter(f), []);
  const small = defaultAzureDesign(); small.chunk = { strategy: "FIXED_SIZE", maxTokens: 75, overlapPct: 10 };
  const big = defaultAzureDesign(); big.chunk = { strategy: "FIXED_SIZE", maxTokens: 400, overlapPct: 10 };
  await f.applyDesign(designToAzure(small)); const job = await f.ingest(); assert.equal(job.status, "COMPLETE");
  const n1 = (await f.chunks()).chunks.length;
  await f.applyDesign(designToAzure(big)); await f.ingest(); const n2 = (await f.chunks()).chunks.length;
  assert.ok(n1 > n2, `${n1} > ${n2}`);
  const o = retrievalOptions(defaultAzureDesign());
  const tr = await f.trace("How often must HVAC filters be replaced?", o); assert.ok(tr.results.some((r) => r.final_rank === 1 && /hvac/i.test(r.uri)));
  const rag = await f.rag("How often must HVAC filters be replaced?", o); assert.ok(rag.citations.length && rag.output.text.includes("[doc1]") && rag.grounded);
  const r = await f.retrieve("HVAC filters", o); assert.ok(r.value[0].chunk_id && r.value[0].chunk);
  const refused = await f.rag("What is the CEO's favourite colour?", o); assert.equal(refused.grounded, false);
});
test("golden set scores through the fake (hit rate high on in-scope questions)", async () => {
  const f = createFake(), o = retrievalOptions(defaultAzureDesign()), rows = [];
  for (const g of DEFAULT_GOLDEN) { const tr = await f.trace(g.question, o), rag = await f.rag(g.question, o); rows.push(scoreRow(g, { retrieved: tr.results.filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank), answer: rag.output.text, citations: rag.citations.map((c) => c.uri) }, 4)); }
  assert.ok(aggregate(rows).hitRate >= 0.7, JSON.stringify(aggregate(rows)));
});
test("live trace rows: keyword/vector/fused/reranker mapped, filter drops shown", () => {
  const chunkMap = new Map([["a", { id: "a", uri: "x.txt", text: "ta", tokens: 3, metadata: { title: "x.txt" } }], ["z", { id: "z", uri: "z.txt", text: "tz", tokens: 3, metadata: { title: "z.txt" } }]]);
  const tr = { candidates: [{ chunkId: "a", uri: "x.txt", text: "ta", keyword_score: 2, keyword_rank: 1, vector_score: 0.9, vector_rank: 2, fused_rank: 1, reranker_score: 3.1, reranker_rank: 1, final_rank: 1 }, { chunkId: "b", uri: "y.txt", text: "tb", vector_rank: 1, vector_score: 0.95, fused_rank: 2, final_rank: 2 }], finalOrder: ["a", "b"] };
  const rows = traceRows(tr, chunkMap, { filter: { key: "title", value: "x.txt" } }, 1);
  assert.equal(rows[0].bm25_rank, 1); assert.equal(rows[0].rerank_score, 3.1); assert.equal(rows[0].final_rank, 1); assert.equal(rows[1].final_rank, null);   // top-N=1 cuts b
  assert.ok(rows.find((r) => r.id === "z").filtered_out_reason.includes("metadata filter"));
});
