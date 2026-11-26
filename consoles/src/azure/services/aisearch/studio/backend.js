/* Azure RAG Studio backend: implements common/ragstudio/adapter.js over the existing aisearch ARM adapter (../api.js).
 *  live          Azure AI Search index/datasource/skillset/indexer PUTs, runIndexer + status polling, docs/search, Azure OpenAI chat with
 *                data_sources (on your data) through the ARM proxy, plus the Vyomi inspect extension (chunks + retrieve-trace).
 *  live-limited  same wires, but the service has no inspect extension: corpus and per-stage views are limited (final score only).
 *  fake          in-browser demo corpus (fake.js), identical shapes. */
import * as api from "../api.js";
import { countTokens, detectLang } from "../../../../common/ragstudio/engine.js";
import { NAMES, chatBody, queryBody } from "./azureMap.js";
import { createFake } from "./fake.js";

const IX = NAMES.index;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ignore = (p) => p.catch(() => null);
const inspectError = (m) => Object.assign(new Error(m), { code: "InspectUnavailable" });

/** Normalise one retrieve-trace candidate to the common TraceRow. `finalK` = how many of the server's ordered results the design keeps. */
export function traceRows(tr, chunkMap, o, finalK) {
  const cand = tr.candidates || [], finals = (tr.finalOrder || []).slice(0, finalK);
  const rows = cand.map((c) => {
    const ch = chunkMap.get(c.chunkId) || {}, fin = finals.indexOf(c.chunkId);
    return { id: c.chunkId, uri: c.uri || ch.uri || "", text: c.text || ch.text || "", tokens: ch.tokens || countTokens(c.text || ""), metadata: ch.metadata || {},
      vector_score: c.vector_score, vector_rank: c.vector_rank, bm25_score: c.keyword_score, bm25_rank: c.keyword_rank,
      fused_rank: c.fused_rank ?? c.vector_rank ?? c.keyword_rank ?? null, rerank_score: c.reranker_score ?? null, rerank_rank: c.reranker_rank ?? null,
      filtered_out_reason: null, final_rank: fin >= 0 ? fin + 1 : null };
  });
  if (o.filter) {   // show what the metadata filter removed (the engine filters before scoring, so these have no scores)
    const key = o.filter.key, ids = new Set(rows.map((r) => r.id));
    [...chunkMap.values()].filter((c) => !ids.has(c.id) && String(c.metadata?.[key]) !== String(o.filter.value)).slice(0, 3).forEach((c) =>
      rows.push({ id: c.id, uri: c.uri, text: c.text, tokens: c.tokens, metadata: c.metadata, vector_score: null, vector_rank: null, bm25_score: null, bm25_rank: null, fused_rank: null, rerank_score: null, filtered_out_reason: `metadata filter (${key} = "${o.filter.value}")`, final_rank: null }));
  }
  return rows;
}
const toChunk = (c) => ({ id: c.id, uri: c.documentUri || c.uri || c.id, text: c.text, tokens: c.tokenCount || countTokens(c.text), metadata: { ...(c.metadata || {}), ...(c.section ? { section: c.section } : {}) },
  pii: c.pii && !["ok", "clean", "none"].includes(c.pii) ? [].concat(c.pii) : [], lang: detectLang(c.text), embedding: c.vector || undefined, position: c.projection2d || undefined });

export async function openLive({ rg, name }) {
  const svc = await api.getService(rg, name);
  const keys = await api.adminKeys(rg, name);
  const [stor, aoai] = await Promise.all([ignore(api.listStorageAccounts()), ignore(api.listOpenAiAccounts())]);
  const aoaiAccts = await Promise.all((aoai || []).map(async (a) => ({ id: a.id, name: a.name, deployments: ((await ignore(api.listDeployments(a.id))) || []).map((d) => ({ name: d.name, model: d.properties?.model?.name })) })));
  const options = { storageAccounts: (stor || []).map((s) => s.name), aoai: aoaiAccts };
  const emb = (a) => a.deployments.find((d) => /embed/i.test(d.model || d.name))?.name, chat = (a) => a.deployments.find((d) => /gpt|chat/i.test(d.model || d.name))?.name;
  const a0 = aoaiAccts[0];
  const env = { storage: { account: options.storageAccounts[0] || "", key: "x" }, aoai: { account: a0?.name || "", embedDeployment: (a0 && emb(a0)) || "embed", chatDeployment: (a0 && chat(a0)) || "chat" } };
  // probe the inspect extension with a throw-away index (needs an existing index to answer; a missing one answers the same on old and new builds)
  let inspectOk = false;
  try { await api.indexes.put(rg, name, "ragstudio-probe", { fields: [{ name: "id", type: "Edm.String", key: true }] }); await api.inspectChunks(rg, name, "ragstudio-probe"); inspectOk = true; } catch { /* limited */ }
  await ignore(api.indexes.remove(rg, name, "ragstudio-probe"));
  let chunkMap = new Map(), dims = 0;
  const finalK = (o) => (o.rerank ? +o.rerankTopN : +o.numberOfResults);
  const endpoint = svc.properties?.endpoint || `https://${name}.search.windows.net/`;
  const self = {
    mode: inspectOk ? "live" : "live-limited", label: `${inspectOk ? "Live" : "Live (limited, no inspect API)"}: ${name} / ${IX}`, env, options, service: svc,
    async listCorpora() { return api.indexes.list(rg, name); },
    /** spec = azureMap.designToAzure(design, be.env): index, parents, datasource, skillset, indexer. */
    async applyDesign(spec) {
      dims = spec.dims;
      await ignore(api.indexers.remove(rg, name, NAMES.indexer)); await ignore(api.skillsets.remove(rg, name, NAMES.skillset));
      await ignore(api.indexes.remove(rg, name, IX)); await ignore(api.indexes.remove(rg, name, NAMES.parents));
      await api.indexes.put(rg, name, NAMES.parents, spec.parents); await api.indexes.put(rg, name, IX, spec.index);
      await api.datasources.put(rg, name, NAMES.datasource, spec.datasource); await api.skillsets.put(rg, name, NAMES.skillset, spec.skillset);
      await api.indexers.put(rg, name, NAMES.indexer, spec.indexer);
      chunkMap = new Map();
      return { index: IX, skillset: NAMES.skillset };
    },
    async ingest() {
      await api.runIndexer(rg, name, NAMES.indexer);
      let st = await api.indexerStatus(rg, name, NAMES.indexer);
      for (let i = 0; i < 120 && (st.status === "running" && (!st.lastResult || st.lastResult.status === "inProgress")); i++) { await sleep(500); st = await api.indexerStatus(rg, name, NAMES.indexer); }
      const r = st.lastResult || {}, count = await ignore(api.indexCount(rg, name, IX));
      chunkMap = new Map();
      return { status: r.status === "success" ? "COMPLETE" : "FAILED", statistics: { numberOfNewDocumentsIndexed: r.itemsProcessed ?? 0, numberOfDocumentsFailed: r.itemsFailed ?? 0, chunksAfter: typeof count === "number" ? count : undefined }, errors: r.errors, raw: st };
    },
    async chunks() {
      if (!inspectOk) throw inspectError("The search service has no Vyomi inspect API (GET .../indexes/{index}/chunks); corpus views need it.");
      const r = await api.inspectChunks(rg, name, IX, false);
      const chunks = (r.chunks || []).map(toChunk); chunkMap = new Map(chunks.map((c) => [c.id, c]));
      return { index: IX, embeddingModel: `${r.dimensions || dims || "?"}-dim embeddings (${env.aoai.embedDeployment})`, chunks };
    },
    async trace(query, o) {
      const body = queryBody(query, o), t0 = performance.now();
      if (!inspectOk) {   // limited: only the final order exists
        const r = await api.searchDocs(rg, name, IX, body), rs = r.value || [];
        return { query, options: o, queryEmbedding: null, latencyMs: { total: +(performance.now() - t0).toFixed(1) }, confidence: rs[0]?.["@search.score"] ?? 0,
          results: rs.map((d, i) => ({ id: d.chunk_id, uri: d.title || "", text: d.chunk || "", tokens: 0, metadata: {}, vector_score: d["@search.score"], vector_rank: i + 1, bm25_score: null, bm25_rank: null, fused_rank: i + 1, rerank_score: d["@search.rerankerScore"] ?? null, filtered_out_reason: null, final_rank: i + 1 <= finalK(o) ? i + 1 : null })) };
      }
      if (!chunkMap.size) await self.chunks();
      const r = await api.inspectTrace(rg, name, IX, body), tr = r.trace || {};
      const results = traceRows(tr, chunkMap, o, finalK(o)), top = results.find((x) => x.final_rank === 1);
      return { query, options: o, queryEmbedding: null, results, searchType: tr.searchType, semanticRanker: tr.semanticRanker, latencyMs: { search: +(performance.now() - t0).toFixed(1), total: +(performance.now() - t0).toFixed(1) },
        confidence: top ? (top.rerank_score != null ? top.rerank_score / 4 : top.vector_score ?? (top.bm25_rank ? 1 / top.bm25_rank : 0)) : 0 };
    },
    retrieve(query, o) { return api.searchDocs(rg, name, IX, queryBody(query, o)); },
    async rag(query, o) {
      const acct = aoaiAccts.find((a) => a.name === env.aoai.account);
      if (!acct) throw Object.assign(new Error("No Azure OpenAI account with a chat deployment was found in this subscription; create one (Foundry or Azure OpenAI) and refresh."), { code: "NoOpenAI" });
      const res = await api.openaiChat(acct.id, env.aoai.chatDeployment, chatBody(query, o, { endpoint, key: keys.primaryKey, threshold: o.threshold }));
      const msg = res.choices?.[0]?.message || {}, cits = (msg.context?.citations || []).map((c) => ({ ...c, uri: c.title || c.filepath || c.url || c.chunk_id }));
      return { output: { text: msg.content || "" }, citations: o.citations === false ? [] : cits, guardrailAction: res.choices?.[0]?.finish_reason === "content_filter" ? "INTERVENED" : "NONE", grounded: cits.length > 0, intent: msg.context?.intent, raw: res };
    },
  };
  return self;
}

/** Live on the chosen search service if reachable, otherwise the demo fake (with the reason, so the UI can say why). */
export async function openBackend(prefer = "auto", target = {}) {
  if (prefer === "fake" || !target.name) return { ...createFake(), reason: prefer === "fake" ? "Demo corpus selected." : "No search service selected; showing the in-browser demo corpus." };
  try { return await openLive(target); }
  catch (e) { if (prefer === "live") throw e; return { ...createFake(), reason: `Search service ${target.name} not reachable (${e.message}); showing the in-browser demo corpus.` }; }
}
