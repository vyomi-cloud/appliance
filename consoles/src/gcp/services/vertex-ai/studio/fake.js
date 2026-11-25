/* GCP fake of the RAG Engine lane: the neutral retrieval core (common/ragstudio/fake.js) over a gs:// copy of the demo corpus, in Vertex AI shapes
 * (ragCorpora, :retrieveContexts, generateContent with a retrieval tool -> groundingMetadata). Used when no simulator corpus is reachable. */
import * as E from "../../../../common/ragstudio/engine.js";
import { CORPUS, createFakeCore } from "../../../../common/ragstudio/fake.js";
import { apiToDesign } from "./gcpMap.js";

export const GCP_CORPUS = CORPUS.map((d) => ({ ...d, uri: d.uri.replace("s3://", "gs://") }));
const stem = (x) => x.replace(/(ing|ed|es|s)$/, "");

export function createFake(corpus = GCP_CORPUS) {
  const corp = { name: "projects/demo/locations/us-central1/ragCorpora/1000000000000001", displayName: "facilities-corpus", corpusStatus: { state: "ACTIVE" } };
  let transformation = { ragFileChunkingConfig: { fixedLengthChunking: { chunkSize: 240, chunkOverlap: 48 } } };
  const core = createFakeCore(corpus, { chunkConfig: () => apiToDesign(transformation).chunk, kbId: "1000000000000001" });
  const api = {
    ...core, mode: "fake", label: "Demo corpus (in-browser fake)", corpus: corp,
    async listCorpora() { return [corp]; },
    async applyDesign(a) { transformation = a.transformation; return { transformation }; },
    async chunks() { const r = await core.chunks(); return { ragCorpus: corp.name, embeddingModel: r.embeddingModel, chunks: r.chunks }; },
    async retrieve(query, o) {
      const tr = await api.trace(query, o), fin = tr.results.filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank);
      return { contexts: { contexts: fin.map((r) => ({ sourceUri: r.uri, sourceDisplayName: r.uri.split("/").pop(), text: r.text, score: r.vector_score, distance: +(1 - r.vector_score).toFixed(6), ...(r.rerank_score != null ? { vyomiRerankScore: r.rerank_score } : {}) })) } };
    },
    async rag(query, o) {
      const tr = await api.trace(query, o), fin = tr.results.filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank);
      const refuse = { output: { text: "I cannot answer that from the corpus: no sufficiently relevant source was found." }, citations: [], guardrailAction: "NONE", grounded: false };
      if (!fin.length || tr.confidence < o.threshold) return refuse;
      const q = E.contentTokens(query).map(stem), picks = [];
      for (const r of fin.slice(0, 3)) for (const s of E.splitSentences(r.text)) { const st = new Set(E.contentTokens(s).map(stem)), cov = q.filter((x) => st.has(x)).length / Math.max(1, q.length); if (cov > 0.3 && !picks.some((p) => p.s === s)) picks.push({ s, cov, r }); }
      picks.sort((a, b) => b.cov - a.cov);
      const use = picks.slice(0, 2);
      if (!use.length) return refuse;
      let text = ""; const cit = [];
      for (const p of use) { text += (text ? " " : "") + p.s; cit.push({ generatedResponsePart: { textResponsePart: { text: p.s } }, retrievedReferences: [{ content: { text: p.r.text }, location: { uri: p.r.uri }, metadata: p.r.metadata }] }); }
      return { output: { text }, citations: o.citations === false ? [] : cit, guardrailAction: "NONE", grounded: true };
    },
  };
  return api;
}
