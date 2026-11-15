/* RAG Studio backend: one interface, two implementations.
 *  - live: the REAL bedrock-agent (UpdateDataSource, StartIngestionJob, GetIngestionJob), bedrock-agent-runtime (Retrieve, RetrieveAndGenerate)
 *    wires, plus the Vyomi inspect extension GET/POST {wire}/_vyomi/kb/{kbId}/chunks | retrieve-trace (chunk vectors + per-stage trace).
 *  - fake: in-browser demo corpus (fake.js), identical shapes.
 * If the live KB exists but the inspect extension is absent, mode is "live-limited": apply/ingest/retrieve/generate work, corpus + stage-score views do not. */
import { awsRest, WIRE_BASE, WireError, authHeader, backendReady } from "../../../../common/wire.js";
import { createFake } from "./fake.js";
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
  try { await inspect(id, "chunks?limit=1"); } catch { inspectOk = false; }
  const api = {
    mode: inspectOk ? "live" : "live-limited", label: inspectOk ? `Live: ${KB_NAME} (${id})` : `Live (limited, no inspect API): ${KB_NAME}`, kb, hasInspect: inspectOk,
    async listKbs() { return list; },
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
    async chunks() { if (!inspectOk) throw new WireError(404, "InspectUnavailable", "The backend has no /_vyomi/kb inspect API; corpus views need it."); return inspect(id, "chunks"); },
    async trace(query, o) {
      if (inspectOk) return inspect(id, "retrieve-trace", { method: "POST", body: JSON.stringify({ query, options: o }) });
      const t0 = performance.now(), rs = await api.retrieve(query, o).then((r) => r.retrievalResults || []);   // limited: only the final score exists
      return { query, options: o, queryEmbedding: null, latencyMs: { total: +(performance.now() - t0).toFixed(1) }, confidence: rs[0]?.score ?? 0,
        results: rs.map((r, i) => ({ id: `r${i}`, uri: r.location?.s3Location?.uri || "", text: r.content?.text || "", tokens: 0, metadata: r.metadata || {}, vector_score: r.score, vector_rank: i + 1, bm25_score: null, bm25_rank: null, fused_rank: i + 1, rerank_score: null, filtered_out_reason: null, final_rank: i + 1 })) };
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
