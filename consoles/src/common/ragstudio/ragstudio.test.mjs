// node --test src/common/ragstudio/ragstudio.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { defaultDesign, applyPreset, lintDesign, scoreRow, aggregate, DEFAULT_GOLDEN } from "./engine.js";
import { toDocument, fromDocument, validate, SCHEMA } from "./document.js";
import { checkAdapter } from "./adapter.js";
import { createFakeCore } from "./fake.js";
import { createFake } from "../../aws/services/bedrock/studio/fake.js";
import { designToApi, apiToDesign } from "../../aws/services/bedrock/studio/engine.js";

test("document round-trips and validates for every cloud", () => {
  for (const cloud of ["aws", "gcp", "azure"]) {
    const d = applyPreset(defaultDesign(), "policy-manuals");
    const doc = toDocument(d, cloud);
    assert.equal(doc.schema, SCHEMA);
    assert.deepEqual(validate(doc), []);
    const back = fromDocument(JSON.parse(JSON.stringify(doc)));
    assert.deepEqual(back.design.chunk, d.chunk);
    assert.deepEqual(back.design.retrieve, d.retrieve);
    assert.deepEqual(back.design.rerank, d.rerank);
    assert.equal(back.golden.length, DEFAULT_GOLDEN.length);
  }
});
test("validate rejects bad documents", () => {
  const doc = toDocument(defaultDesign(), "aws");
  assert.ok(validate({ ...doc, cloud: "oci" }).some((m) => m.startsWith("cloud")));
  assert.ok(validate({ ...doc, schema: "x" }).length);
  assert.ok(validate({ ...doc, rerank: { enabled: true, topN: 99 } }).some((m) => m.startsWith("rerank.topN")));
  assert.ok(validate({ ...doc, retrieve: { ...doc.retrieve, hybridWeight: 2 } }).length);
});
test("filter survives the document", () => {
  const d = defaultDesign(); d.retrieve.filterKey = "department"; d.retrieve.filterValue = "hvac";
  assert.deepEqual(fromDocument(toDocument(d, "gcp")).design.retrieve.filterValue, "hvac");
});
test("AWS mapping still works via the shim", () => {
  const api = designToApi(defaultDesign());
  assert.equal(api.dataSource.vectorIngestionConfiguration.chunkingConfiguration.chunkingStrategy, "FIXED_SIZE");
  assert.equal(apiToDesign(api.dataSource.vectorIngestionConfiguration.chunkingConfiguration).chunk.maxTokens, 48);
  assert.deepEqual(lintDesign(defaultDesign()).filter((x) => x.severity === "error"), []);
});
test("AWS fake conforms to the adapter interface and answers", async () => {
  const f = createFake();
  assert.deepEqual(checkAdapter(f), []);
  await f.ingest();
  const tr = await f.trace("How often must HVAC filters be replaced?", { numberOfResults: 8, searchType: "HYBRID", hybridWeight: 0.6, rerank: true, rerankTopN: 4, filter: null, threshold: 0.25 });
  assert.ok(tr.results.some((r) => r.final_rank === 1));
  const rag = await f.rag("How often must HVAC filters be replaced?", { numberOfResults: 8, searchType: "HYBRID", hybridWeight: 0.6, rerank: true, rerankTopN: 4, filter: null, threshold: 0.25, citations: true });
  assert.match(rag.output.text, /90 days/);
});
test("neutral core runs without any cloud code and metrics score", async () => {
  const core = createFakeCore();
  const tr = await core.trace("fire extinguishers inspected", { numberOfResults: 6, searchType: "HYBRID", hybridWeight: 0.5, rerank: false, rerankTopN: 3, filter: null });
  const res = { retrieved: tr.results.map((r) => ({ id: r.id, uri: r.uri, text: r.text })), answer: "", citations: [] };
  const agg = aggregate([scoreRow(DEFAULT_GOLDEN[2], res)]);
  assert.equal(agg.hitRate, 1);
});
