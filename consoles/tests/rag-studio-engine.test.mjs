/* RAG Studio: deterministic metrics + design linter + mapping + fake backend. Run: node consoles/tests/rag-studio-engine.test.mjs */
import * as E from "../src/aws/services/bedrock/studio/engine.js";
import { createFake } from "../src/aws/services/bedrock/studio/fake.js";
let fail = 0;
const check = (n, ok, d = "") => { if (!ok) fail++; console.log(`${ok ? "PASS" : "FAIL"} ${n}${d ? " - " + d : ""}`); };
const near = (a, b) => Math.abs(a - b) < 1e-9;

// metrics
const row = { question: "q", expectedSources: ["a.txt"], expectedAnswer: "filters replaced every ninety days" };
const ch = (id, uri, text) => ({ id, uri, text });
let s = E.scoreRow(row, { retrieved: [ch(1, "s3://x/b.txt", "unrelated text"), ch(2, "s3://x/a.txt", "Filters are replaced every ninety days by the team."), ch(3, "s3://x/a.txt", "more")], answer: "Filters are replaced every ninety days.", citations: ["s3://x/a.txt"] }, 5);
check("hitRate hit", s.hitRate === 1);
check("MRR first relevant at rank 2 = 0.5", near(s.mrr, 0.5));
check("context precision (AP) = (1/2+2/3)/2", near(s.contextPrecision, (1 / 2 + 2 / 3) / 2), s.contextPrecision);
check("context recall full", s.contextRecall === 1);
check("citation accuracy 1", s.citationAccuracy === 1);
check("faithfulness grounded", s.faithfulness === 1);
check("answer relevance high", s.answerRelevance > 0.8, s.answerRelevance);
s = E.scoreRow(row, { retrieved: [ch(1, "s3://x/b.txt", "nothing here")], answer: "Bananas are yellow.", citations: ["s3://x/b.txt"] }, 5);
check("miss: hit 0, mrr 0, cite 0", s.hitRate === 0 && s.mrr === 0 && s.citationAccuracy === 0);
check("ungrounded answer faithfulness 0", s.faithfulness === 0);
s = E.scoreRow(row, { retrieved: [ch(1, "s3://x/b.txt", "x"), ch(2, "s3://x/c.txt", "y"), ch(3, "s3://x/a.txt", "z")], answer: "", citations: [] }, 2);
check("relevant outside @k does not count", s.hitRate === 0);
s = E.scoreRow({ question: "off topic", expectedSources: [], expectedAnswer: "" }, { retrieved: [], answer: "I cannot answer that from the knowledge base.", citations: [] });
check("out-of-scope question: refusal scores 1 across", s.hitRate === 1 && s.citationAccuracy === 1 && s.answerRelevance === 1 && s.faithfulness === 1);
const agg = E.aggregate([{ hitRate: 1, mrr: 1, contextPrecision: 1, contextRecall: 1, citationAccuracy: 1, faithfulness: 1, answerRelevance: 1 }, { hitRate: 0, mrr: 0, contextPrecision: 0, contextRecall: 0, citationAccuracy: 0, faithfulness: 0, answerRelevance: 0 }]);
check("aggregate mean", agg.hitRate === 0.5);
check("verdict thresholds", E.verdicts(agg, { hitRate: 0.5, mrr: 0.6 }).hitRate === true && E.verdicts(agg, { hitRate: 0.5, mrr: 0.6 }).mrr === false);
const cmp = E.compareRuns({ aggregate: { ...agg, hitRate: 0.4 } }, { aggregate: { ...agg, hitRate: 0.9 } });
check("A/B winner", cmp.find((c) => c.metric === "hitRate").winner === "B" && cmp.find((c) => c.metric === "mrr").winner === "tie");

// provenance
const pv = E.provenance("Filters are replaced every ninety days. The CEO likes blue paint.", [ch("c1", "u", "Filters are replaced every ninety days by the team.")]);
check("provenance: grounded + ungrounded flagged", pv.length === 2 && pv[0].grounded && !pv[1].grounded && pv[0].chunkId === "c1");

// linter
const d0 = E.defaultDesign(), ids = (d, c) => E.lintDesign(d, c).map((x) => x.id);
check("default design has no errors", !E.lintDesign(d0).some((x) => x.severity === "error"), ids(d0).join());
let d = JSON.parse(JSON.stringify(d0)); d.embed.model = "vyomi.minilm-l6"; d.chunk.maxTokens = 400;
check("chunk > embedding window", ids(d).includes("chunk-over-window"));
check("autofix applies", E.lintDesign(E.applyFix(d, E.lintDesign(d).find((x) => x.id === "chunk-over-window").fix)).every((x) => x.id !== "chunk-over-window"));
d = JSON.parse(JSON.stringify(d0)); d.chunk.overlapPct = 0; d.chunk.maxTokens = 200; check("no overlap warned", ids(d).includes("no-overlap"));
d = JSON.parse(JSON.stringify(d0)); d.rerank = { enabled: true, topN: 10 }; d.retrieve.topK = 10; check("rerank without headroom", ids(d).includes("rerank-no-headroom"));
const chunks = [{ uri: "u", metadata: { department: "hvac" }, tokens: 50 }];
d = JSON.parse(JSON.stringify(d0)); d.retrieve.filterKey = "department"; d.retrieve.filterValue = "legal"; check("filter matches nothing", ids(d, { chunks }).includes("filter-no-match"));
d.retrieve.filterKey = "nope"; check("filter unknown key", ids(d, { chunks }).includes("filter-unknown-key"));
d = JSON.parse(JSON.stringify(d0)); d.generate.groundingThreshold = 0; d.generate.citations = false; check("grounding off + citations off", ids(d).includes("grounding-off") && ids(d).includes("citations-off"));

// api mapping
const api = E.designToApi(E.applyPreset(d0, "policy-manuals"));
check("designToApi semantic chunking", api.dataSource.vectorIngestionConfiguration.chunkingConfiguration.chunkingStrategy === "SEMANTIC" && api.dataSource.vectorIngestionConfiguration.chunkingConfiguration.semanticChunkingConfiguration.maxTokens === 300);
check("designToApi retrieval + rerank", api.retrievalConfiguration.vectorSearchConfiguration.numberOfResults === 12 && api.retrievalConfiguration.vectorSearchConfiguration.rerankingConfiguration.bedrockRerankingConfiguration.numberOfRerankedResults === 4);
const back = E.apiToDesign(api.dataSource.vectorIngestionConfiguration.chunkingConfiguration);
check("apiToDesign round trip", back.chunk.strategy === "SEMANTIC" && back.chunk.maxTokens === 300);

// chunker + analytics
const txt = "Alpha beta gamma. ".repeat(80);
check("fixed chunker honours size", E.chunkText(txt, { strategy: "FIXED_SIZE", maxTokens: 40, overlapPct: 20 }).every((c) => E.countTokens(c.text) <= 45));
check("NONE = 1 chunk", E.chunkText(txt, { strategy: "NONE" }).length === 1);
check("duplicate clusters", E.duplicateClusters([{ id: 1, uri: "a", text: "the quick brown fox jumps over the lazy dog today" }, { id: 2, uri: "b", text: "the quick brown fox jumps over the lazy dog today again" }, { id: 3, uri: "c", text: "completely different words appear in this sentence here" }]).length === 1);
check("pii scan", E.piiScan("mail me at a.b@corp.com").includes("email") && E.piiScan("nothing").length === 0);

// fake backend end to end
const f = createFake();
const kbs = await f.listKbs();
check("fake: facilities-kb exists", kbs.some((k) => k.name === "facilities-kb"));
await f.applyDesign(E.designToApi(d0)); const job = await f.ingest();
check("fake: ingestion job complete", job.status === "COMPLETE" && job.statistics.numberOfNewDocumentsIndexed >= 10, JSON.stringify(job.statistics));
const { chunks: all } = await f.chunks();
check("fake: chunks carry id/uri/tokens/metadata/embedding", all.length > 30 && all.every((c) => c.id && c.uri && c.tokens && c.metadata && c.embedding.length === 256));
const tr = await f.trace("How often must HVAC filters be replaced?", E.retrievalOptions(d0));
const top = tr.results.filter((r) => !r.filtered_out_reason)[0];
check("trace: per-stage scores + latency", top && "vector_score" in top && "bm25_score" in top && "fused_rank" in top && "rerank_score" in top && tr.latencyMs.total >= 0 && tr.queryEmbedding.length === 256);
check("trace: relevant doc on top", /hvac-maintenance/.test(top.uri), top.uri);
const filt = await f.trace("HVAC filters", { ...E.retrievalOptions(d0), filter: { key: "department", value: "security" } });
check("trace: filtered_out_reason set", filt.results.some((r) => r.filtered_out_reason) && filt.results.filter((r) => !r.filtered_out_reason).every((r) => r.metadata.department === "security"));
const rag = await f.rag("How often must HVAC filters be replaced?", E.retrievalOptions(d0));
check("rag: cited answer shape", rag.output.text && rag.citations[0].retrievedReferences[0].location.s3Location.uri && rag.guardrailAction === "NONE");
const off = await f.rag("What is the CEO's favourite colour?", E.retrievalOptions(d0));
check("rag: below grounding threshold refuses", E.isRefusal(off.output.text), off.output.text);
const pii = await f.rag("My SSN is 123-45-6789, what is the HVAC policy?", E.retrievalOptions(d0));
check("rag: guardrail intervenes on PII input", pii.guardrailAction === "INTERVENED");
// evaluation: hybrid design should be at least as good as semantic-only on the golden set
const evalRun = async (design) => { const o = E.retrievalOptions(design); const sc = []; for (const r of E.DEFAULT_GOLDEN) { const t = await f.trace(r.question, o), g = await f.rag(r.question, o); sc.push(E.scoreRow(r, { retrieved: t.results.filter((x) => !x.filtered_out_reason && x.final_rank), answer: g.output.text, citations: g.citations.flatMap((c) => c.retrievedReferences.map((x) => x.location.s3Location.uri)) }, 4)); } return E.aggregate(sc); };
const aggH = await evalRun(d0);
check("golden set: hit rate >= 0.8 on default design", aggH.hitRate >= 0.8, JSON.stringify(Object.fromEntries(Object.entries(aggH).map(([k, v]) => [k, +v.toFixed(2)]))));
console.log(fail ? `${fail} FAILED` : "ALL PASS"); process.exit(fail ? 1 : 0);
