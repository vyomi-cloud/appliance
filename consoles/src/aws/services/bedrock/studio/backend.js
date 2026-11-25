/* RAG Studio backend: one interface, two implementations.
 *  - live: the REAL bedrock-agent (UpdateDataSource, StartIngestionJob, GetIngestionJob), bedrock-agent-runtime (Retrieve, RetrieveAndGenerate)
 *    wires, plus the Vyomi inspect extension GET/POST {wire}/_vyomi/kb/{kbId}/chunks | retrieve-trace (chunk vectors + per-stage trace).
 *  - fake: in-browser demo corpus (fake.js), identical shapes.
 * If the live KB exists but the inspect extension is absent, mode is "live-limited": apply/ingest/retrieve/generate work, corpus + stage-score views do not. */
import { awsRest, WIRE_BASE, WireError, authHeader, backendReady } from "../../../../common/wire.js";
import { createFake } from "./fake.js";
import { detectLang } from "./engine.js";
import { modelArn, NOVA } from "../Common.jsx";

const B = (m, p, o) => awsRest("bedrock", m, p, o);
const R = (m, p, o) => awsRest("bedrock", m, p, o);
const KB_NAME = "facilities-kb";
const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms))]);

async function inspect(kbId, path, init) {
  const r = await fetch(`${WIRE_BASE}/_vyomi/kb/${kbId}/${path}`, { ...init, headers: { ...authHeader("bedrock"), "content-type": "application/json" } });
  if (!r.ok) throw new WireError(r.status, "InspectUnavailable", `inspect API ${path}: HTTP ${r.status}`, "");
  return r.json();
}

function toRetrieveOptions(o) {
  const v = { numberOfResults: o.numberOfResults, overrideSearchType: o.searchType === "SEMANTIC" ? "SEMANTIC" : "HYBRID" };
  if (o.filter) v.filter = { equals: { key: o.filter.key, value: o.filter.value } };
  if (o.rerank) v.rerankingConfiguration = { type: "BEDROCK_RERANKING_MODEL", bedrockRerankingConfiguration: { modelConfiguration: { modelArn: modelArn("amazon.rerank-v1:0") }, numberOfRerankedResults: o.rerankTopN } };
  return { vectorSearchConfiguration: v };
}

export async function openLive() {
  await Promise.race([backendReady(), new Promise((r) => setTimeout(r, 20000))]);   // Nano: the in-browser backend boots after the page mounts
  const list = await withTimeout(B("POST", "/knowledgebases/", { body: {} }).then((r) => r.knowledgeBaseSummaries || []), 8000);
  const kb = list.find((k) => k.name === KB_NAME);
  if (!kb) throw new Error(`no knowledge base named ${KB_NAME}`);
  const id = kb.knowledgeBaseId;
  const dsList = await B("POST", `/knowledgebases/${id}/datasources/`, { body: {} }).then((r) => r.dataSourceSummaries || []);
  const ds = dsList[0];
  let inspectOk = true;
  try { await inspect(id, "chunks"); } catch { inspectOk = false; }
  let chunkMap = new Map();
  const limitedTrace = async (query, o) => {
    const t0 = performance.now(), rs = await api.retrieve(query, o).then((r) => r.retrievalResults || []);   // limited: only the final score exists
    return { query, options: o, queryEmbedding: null, latencyMs: { total: +(performance.now() - t0).toFixed(1) }, confidence: rs[0]?.score ?? 0,
      results: rs.map((r, i) => ({ id: `r${i}`, uri: r.location?.s3Location?.uri || "", text: r.content?.text || "", tokens: 0, metadata: r.metadata || {}, vector_score: r.score, vector_rank: i + 1, bm25_score: null, bm25_rank: null, fused_rank: i + 1, rerank_score: null, filtered_out_reason: null, final_rank: i + 1 })) };
  };
  const api = {
    mode: inspectOk ? "live" : "live-limited", label: inspectOk ? `Live: ${KB_NAME} (${id})` : `Live (limited, no inspect API): ${KB_NAME}`, kb, hasInspect: inspectOk,
    async listKbs() { return list; },
    async listCorpora() { return list; },
    async getDataSource() { return ds ? B("GET", `/knowledgebases/${id}/datasources/${ds.dataSourceId}`).then((r) => r.dataSource) : null; },
    async applyDesign(a) {
      if (!ds) throw new Error("facilities-kb has no data source to apply the design to");
      const cur = await api.getDataSource();
      const body = { name: cur.name, dataSourceConfiguration: cur.dataSourceConfiguration, vectorIngestionConfiguration: a.dataSource.vectorIngestionConfiguration };
      return B("PUT", `/knowledgebases/${id}/datasources/${ds.dataSourceId}`, { body }).then((r) => r.dataSource);
    },
    async ingest() {
      let job = await B("PUT", `/knowledgebases/${id}/datasources/${ds.dataSourceId}/ingestionjobs/`, { body: {} }).then((r) => r.ingestionJob);
      for (let i = 0; i < 120 && ["STARTING", "IN_PROGRESS"].includes(job.status); i++) { await new Promise((r) => setTimeout(r, 1000)); job = await B("GET", `/knowledgebases/${id}/datasources/${ds.dataSourceId}/ingestionjobs/${job.ingestionJobId}`).then((r) => r.ingestionJob); }
      return job;
    },
    async chunks() {
      if (!inspectOk) throw new WireError(404, "InspectUnavailable", "The backend has no /_vyomi/kb inspect API; corpus views need it.");
      const r = await inspect(id, "chunks?vectors=true");
      const chunks = (r.chunks || []).map((c) => ({ id: c.id, uri: c.documentUri || c.uri, text: c.text, tokens: c.tokenCount || c.tokens, metadata: { ...(c.metadata || {}), ...(c.section ? { section: c.section } : {}) },
        pii: c.pii && !["ok", "clean", "none"].includes(c.pii) ? [].concat(c.pii) : [], lang: detectLang(c.text), embedding: c.vector || c.embedding, ...(c.vector || c.embedding ? {} : { position: c.projection2d }) }));
      chunkMap = new Map(chunks.map((c) => [c.id, c]));
      return { knowledgeBaseId: id, embeddingModel: `${r.dimensions || "?"}-dim local embeddings`, chunks };
    },
    async trace(query, o) {
      if (!inspectOk) return limitedTrace(query, o);
      if (!chunkMap.size) await api.chunks();
      const body = { retrievalQuery: { text: query }, retrievalConfiguration: toRetrieveOptions(o), ...(o.searchType === "SEMANTIC" ? {} : { hybridWeight: +(1 - o.hybridWeight).toFixed(3) }) };   // server weight is the LEXICAL share
      const t0 = performance.now(), r = await inspect(id, "retrieve-trace", { method: "POST", body: JSON.stringify(body) });
      const tr = r.trace || {}, cand = tr.candidates || [], finals = (r.retrievalResults || []).map((x) => x.metadata?.["x-amz-bedrock-kb-chunk-id"]);
      const live = cand.filter((c) => !c.filtered_out_reason || !/filter/.test(c.filtered_out_reason));
      const vr = new Map([...live].sort((a, b) => b.vector_score - a.vector_score).map((c, i) => [c.chunkId, i + 1])), br = new Map([...live].sort((a, b) => b.bm25_score - a.bm25_score).map((c, i) => [c.chunkId, i + 1]));
      const pool = o.numberOfResults;
      const keep = cand.filter((c) => (c.fused_rank && c.fused_rank <= pool) || c.returned);
      const dropped = cand.filter((c) => /filter/.test(c.filtered_out_reason || "")).sort((a, b) => b.vector_score - a.vector_score).slice(0, 3);
      const row = (c) => { const ch = chunkMap.get(c.chunkId) || {}; const filt = /filter/.test(c.filtered_out_reason || ""); const fin = finals.indexOf(c.chunkId);
        return { id: c.chunkId, uri: c.uri, text: ch.text || "", tokens: ch.tokens || 0, metadata: ch.metadata || {}, vector_score: c.vector_score, vector_rank: filt ? null : vr.get(c.chunkId), bm25_score: filt ? null : c.bm25_score, bm25_rank: filt ? null : br.get(c.chunkId), fused_rank: c.fused_rank, rerank_score: c.rerank_score, filtered_out_reason: filt ? `${c.filtered_out_reason} (${o.filter?.key} = "${o.filter?.value}")` : null, final_rank: fin >= 0 ? fin + 1 : null }; };
      const lat = tr.latencyMs || {}; lat.total = +(performance.now() - t0).toFixed(1);
      return { query, options: o, queryEmbedding: null, latencyMs: lat, confidence: r.retrievalResults?.[0]?.score ?? 0, results: [...keep, ...dropped].map(row), searchType: tr.searchType };
    },
    retrieve(query, o) { return R("POST", `/knowledgebases/${id}/retrieve`, { body: { retrievalQuery: { text: query }, retrievalConfiguration: toRetrieveOptions(o) } }); },
    rag(query, o) { return R("POST", "/retrieveAndGenerate", { body: { input: { text: query }, retrieveAndGenerateConfiguration: { type: "KNOWLEDGE_BASE", knowledgeBaseConfiguration: { knowledgeBaseId: id, modelArn: modelArn(NOVA), retrievalConfiguration: toRetrieveOptions(o), generationConfiguration: { inferenceConfig: { textInferenceConfig: { temperature: 0.1 } } } } } } }).then((r) => ({ ...r, citations: o.citations === false ? [] : r.citations })); },
  };
  return api;
}

/** Live if reachable, otherwise the demo fake (with the reason, so the UI can say why). */
export async function openBackend(prefer = "auto") {
  if (prefer === "fake") return { ...createFake(), reason: "Demo corpus selected." };
  try { return await openLive(); }
  catch (e) { if (prefer === "live") throw e; return { ...createFake(), reason: `Live ${KB_NAME} not reachable (${e.message}); showing the in-browser demo corpus.` }; }
}
