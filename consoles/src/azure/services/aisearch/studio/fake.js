/* Azure RAG Studio fake: the neutral retrieval core (common/ragstudio/fake.js) behind the Azure adapter, so the Studio works with no
 * simulator (demo corpus). Retrieval math is real (BM25 + hashed vectors + weighted RRF + term-coverage rerank); only the corpus is canned.
 * The design really round-trips through the Azure shapes: applyDesign stores the SplitSkill and the chunker re-derives its config from it. */
import * as E from "../../../../common/ragstudio/engine.js";
import { CORPUS, createFakeCore } from "../../../../common/ragstudio/fake.js";
import { NAMES, azureToChunk, defaultAzureDesign, designToAzure } from "./azureMap.js";

export function createFake(corpus = CORPUS) {
  let skillset = designToAzure(defaultAzureDesign()).skillset;
  const core = createFakeCore(corpus, { chunkConfig: () => azureToChunk(skillset), kbId: NAMES.index });
  const hit = (r, rank) => ({ "@search.score": r.rerank_score ?? r.vector_score, ...(r.rerank_score != null ? { "@search.rerankerScore": +(r.rerank_score * 4).toFixed(3) } : {}), chunk_id: r.id, title: r.uri.split("/").pop(), chunk: r.text, rank });
  const api = {
    ...core, mode: "fake", label: "Demo corpus (in-browser fake of Azure AI Search)", env: {}, options: { storageAccounts: [], aoai: [] },
    async listCorpora() { return [{ name: NAMES.index, documentCount: null }]; },
    async applyDesign(spec) { skillset = spec.skillset; return { skillset: spec.skillset.name, index: spec.index.name }; },
    async ingest() {
      const job = await core.ingest(), s = job.statistics || {};
      return { status: "COMPLETE", statistics: { numberOfNewDocumentsIndexed: s.numberOfNewDocumentsIndexed ?? corpus.length, numberOfDocumentsFailed: 0, chunksAfter: s.chunksAfter }, raw: job };
    },
    async retrieve(query, o) {
      const tr = await api.trace(query, o), fin = tr.results.filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank);
      return { value: fin.map((r, i) => hit(r, i + 1)), "@odata.count": tr.results.length };
    },
    async rag(query, o) {
      if (E.piiScan(query).length || /\b(password|salary|home address)\b/i.test(query)) return { output: { text: "The requested information is not in the retrieved data." }, citations: [], guardrailAction: "NONE", grounded: false };
      const tr = await api.trace(query, o), fin = tr.results.filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank);
      const none = { output: { text: "The requested information is not in the retrieved data." }, citations: [], guardrailAction: "NONE", grounded: false };
      if (!fin.length || tr.confidence < o.threshold) return none;
      const q = E.contentTokens(query).map((x) => x.replace(/(ing|ed|es|s)$/, "")), picks = [];
      for (const r of fin.slice(0, 3)) for (const s of E.splitSentences(r.text)) { const st = new Set(E.contentTokens(s).map((x) => x.replace(/(ing|ed|es|s)$/, ""))), cov = q.filter((x) => st.has(x)).length / Math.max(1, q.length); if (cov > 0.3 && !picks.some((p) => p.s === s)) picks.push({ s, cov, r }); }
      picks.sort((a, b) => b.cov - a.cov); const use = picks.slice(0, 2);
      if (!use.length) return none;
      const text = use.map((p, i) => `${p.s} [doc${i + 1}]`).join(" ");
      const cit = use.map((p, i) => ({ content: p.r.text, title: p.r.uri.split("/").pop(), url: null, filepath: p.r.uri, chunk_id: String(i), uri: p.r.uri }));
      return { output: { text }, citations: o.citations === false ? [] : cit, guardrailAction: "NONE", grounded: true, intent: [query] };
    },
  };
  return api;
}
