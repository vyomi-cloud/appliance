/* GCP RAG Studio backend (adapter: common/ragstudio/adapter.js), three modes:
 *  - live:         the REAL Vertex AI RAG Engine wires (ragCorpora, ragFiles:upload/import, :retrieveContexts, generateContent + retrieval tool)
 *                  plus the Vyomi inspect extension GET/POST /_vyomi/gcp-rag/{project}/{location}/{corpusId}/chunks | retrieve-trace
 *  - live-limited: real wires work, no inspect API: corpus and stage-score views are limited (only the final score exists)
 *  - fake:         in-browser demo corpus (fake.js), identical shapes */
import { restJson, WireError, backendReady } from "../../../../common/wire.js";
import { getProject } from "../../../project.js";
import { detectLang } from "../../../../common/ragstudio/engine.js";
import { createFake, GCP_CORPUS } from "./fake.js";
import { toRagRetrievalConfig, traceRows, designToApi, gcpDefaultDesign, fileIdsFor, retrieveBody, citationsFrom } from "./gcpMap.js";

export const LOCATION = "us-central1";
export const CORPUS_NAME = "facilities-corpus";
export const DEMO_TAG = "vyomi-rag-studio-demo";
const json = (method, path, body, query) => restJson(method, path, { body, query });
const withTimeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms))]);
const parent = () => `/v1/projects/${encodeURIComponent(getProject())}/locations/${LOCATION}`;
const inspectPath = (corpus, op) => `/_vyomi/gcp-rag/${encodeURIComponent(getProject())}/${LOCATION}/${corpus.name.split("/").pop()}/${op}`;

async function pollLro(op) {
  let o = op;
  for (let i = 0; i < 120 && o && o.done === false; i++) { await new Promise((r) => setTimeout(r, 500)); o = await json("GET", `/v1/${op.name}`); }
  return o;
}

export async function listCorpusFiles(corpus) { return (await json("GET", `/v1/${corpus.name}/ragFiles`)).ragFiles || []; }

/** Creates the demo corpus (embedding model config + the facilities documents uploaded as text) so the Studio has something live to work on. */
export async function seedDemoCorpus(design = gcpDefaultDesign()) {
  const a = designToApi(design);
  const op = await json("POST", `${parent()}/ragCorpora`, { displayName: CORPUS_NAME, description: DEMO_TAG, ragEmbeddingModelConfig: a.ragEmbeddingModelConfig });
  const corpus = (await pollLro(op)).response || op.response;
  await uploadDemoDocs(corpus, a);
  return corpus;
}
async function uploadDemoDocs(corpus, a) {
  for (const d of GCP_CORPUS) await json("POST", `/upload/v1/${corpus.name}/ragFiles:upload`, { ragFile: { displayName: d.uri.split("/").pop(), description: DEMO_TAG }, text: d.text, uploadRagFileConfig: { ragFileTransformationConfig: a.transformation } });
}

export async function openLive() {
  await Promise.race([backendReady(), new Promise((r) => setTimeout(r, 20000))]);   // Nano: the in-browser backend boots after the page mounts
  const list = await withTimeout(json("GET", `${parent()}/ragCorpora`).then((r) => r.ragCorpora || []), 8000);
  const corpus = list.find((c) => c.displayName === CORPUS_NAME) || list[0];
  if (!corpus) { const e = new Error(`no RAG corpus in ${getProject()}/${LOCATION}`); e.noCorpus = true; throw e; }
  let inspectOk = true;
  try { await json("GET", inspectPath(corpus, "chunks")); } catch { inspectOk = false; }
  let chunkMap = new Map(), pending = null;
  const limitedTrace = async (query, o) => {
    const t0 = performance.now(), r = await api.retrieve(query, o), cs = r.contexts?.contexts || [];
    return { query, options: o, queryEmbedding: null, latencyMs: { total: +(performance.now() - t0).toFixed(1) }, confidence: cs[0]?.vyomiRerankScore ?? cs[0]?.score ?? 0,
      results: cs.map((c, i) => ({ id: `r${i}`, uri: c.sourceDisplayName || c.sourceUri, text: c.text, tokens: 0, metadata: {}, vector_score: c.score, vector_rank: i + 1, bm25_score: null, bm25_rank: null, fused_rank: i + 1, rerank_score: c.vyomiRerankScore ?? null, filtered_out_reason: null, final_rank: i + 1 })) };
  };
  const api = {
    mode: inspectOk ? "live" : "live-limited", corpus, hasInspect: inspectOk,
    label: inspectOk ? `Live: ${corpus.displayName} (${corpus.name.split("/").pop()})` : `Live (limited, no inspect API): ${corpus.displayName}`,
    async listCorpora() { return list; },
    async applyDesign(a) { pending = a; return { transformation: a.transformation, note: "RAG Engine chunking is applied per file at upload/import; run ingestion to re-chunk." }; },
    async ingest() {
      const a = pending || designToApi(gcpDefaultDesign()), files = await listCorpusFiles(corpus), t0 = Date.now();
      const gcs = files.filter((f) => f.gcsSource), demo = files.filter((f) => f.description === DEMO_TAG);
      if (gcs.length) {
        for (const f of gcs) await json("DELETE", `/v1/${f.name}`);
        const op = await pollLro(await json("POST", `/v1/${corpus.name}/ragFiles:import`, { importRagFilesConfig: a.importRagFilesConfig }));
        const r = op.response || {};
        return { ingestionJobId: `import-${t0}`, status: op.error ? "FAILED" : "COMPLETE", statistics: { numberOfNewDocumentsIndexed: +r.importedRagFilesCount || 0, numberOfDocumentsFailed: +r.failedRagFilesCount || 0 } };
      }
      if (demo.length && demo.length === files.length) {
        for (const f of demo) await json("DELETE", `/v1/${f.name}`);
        await uploadDemoDocs(corpus, a);
        return { ingestionJobId: `upload-${t0}`, status: "COMPLETE", statistics: { numberOfNewDocumentsIndexed: GCP_CORPUS.length, numberOfDocumentsFailed: 0 } };
      }
      throw new WireError(400, "FAILED_PRECONDITION", "This corpus holds directly uploaded files; the RAG Engine cannot re-chunk them. Re-upload them with the new chunk config, or import from a Cloud Storage prefix.", "");
    },
    async chunks() {
      if (!inspectOk) throw new WireError(404, "InspectUnavailable", "The backend has no /_vyomi/gcp-rag inspect API; corpus views need it.", "");
      const r = await json("GET", inspectPath(corpus, "chunks"), undefined, { vectors: "true" });
      const chunks = (r.chunks || []).map((c) => ({ id: c.id, uri: /^gs:\/\//.test(c.documentUri) ? c.documentUri : (c.metadata?.file || c.documentUri), text: c.text, tokens: c.tokenCount, metadata: { ...(c.metadata || {}) },
        pii: Array.isArray(c.pii) ? c.pii : [], lang: detectLang(c.text), embedding: c.vector, ...(c.vector ? {} : { position: c.projection2d }) }));
      chunkMap = new Map(chunks.map((c) => [c.id, c]));
      return { ragCorpus: corpus.name, embeddingModel: `${r.embeddingModel || "local embedder"} (${r.dimensions || "?"}-dim)`, chunks };
    },
    async trace(query, o) {
      if (!inspectOk) return limitedTrace(query, o);
      if (!chunkMap.size) await api.chunks();
      const fileIds = fileIdsFor(o.filter, [...chunkMap.values()]);
      const t0 = performance.now(), r = await json("POST", inspectPath(corpus, "retrieve-trace"), retrieveBody(corpus, query, o, fileIds));
      const cs = r.contexts?.contexts || [], tr = r.trace || {}, finals = (tr.candidates || []).filter((c) => c.final_rank).sort((a, b) => a.final_rank - b.final_rank).map((c) => c.chunkId);
      const lat = { ...(tr.latencyMs || {}) }; lat.total = +(performance.now() - t0).toFixed(1);
      return { query, options: o, queryEmbedding: null, latencyMs: lat, confidence: cs[0]?.vyomiRerankScore ?? cs[0]?.score ?? 0, searchType: tr.searchType, embeddingModel: tr.embeddingModel,
        results: traceRows(tr, o, chunkMap, finals) };
    },
    async retrieve(query, o) {
      const fileIds = fileIdsFor(o.filter, [...chunkMap.values()]);
      return json("POST", `${parent()}:retrieveContexts`, retrieveBody(corpus, query, o, fileIds));
    },
    async rag(query, o) {
      const fileIds = fileIdsFor(o.filter, [...chunkMap.values()]), model = o.model || "gemini-2.0-flash";
      const store = { ragResources: [{ ragCorpus: corpus.name, ...(fileIds ? { ragFileIds: fileIds } : {}) }], ragRetrievalConfig: toRagRetrievalConfig(o) };
      const r = await json("POST", `${parent()}/publishers/google/models/${model}:generateContent`, { contents: [{ role: "user", parts: [{ text: query }] }], tools: [{ retrieval: { vertexRagStore: store } }], generationConfig: { temperature: 0.1, maxOutputTokens: 300 } });
      const cand = r.candidates?.[0] || {}, text = (cand.content?.parts || []).map((p) => p.text || "").join("").trim(), gm = cand.groundingMetadata;
      return { output: { text }, citations: o.citations === false ? [] : citationsFrom(gm), guardrailAction: cand.finishReason === "SAFETY" ? "INTERVENED" : "NONE", grounded: !!(gm?.groundingChunks || []).length };
    },
  };
  return api;
}

/** Live if reachable, otherwise the demo fake (with the reason, so the UI can say why). */
export async function openBackend(prefer = "auto") {
  if (prefer === "fake") return { ...createFake(), reason: "Demo corpus selected." };
  try { return await openLive(); }
  catch (e) { if (prefer === "live") throw e; return { ...createFake(), noCorpus: !!e.noCorpus, reason: e.noCorpus ? `No RAG corpus in this project yet; showing the in-browser demo corpus. Use "Seed demo corpus" to create ${CORPUS_NAME} in the simulator.` : `Live RAG Engine not reachable (${e.message}); showing the in-browser demo corpus.` }; }
}
