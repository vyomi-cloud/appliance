/* AWS fake of the knowledge lane: the neutral retrieval core (common/ragstudio/fake.js) wrapped in bedrock-agent / bedrock-agent-runtime shapes. */
import * as E from "./engine.js";
import { CORPUS, createFakeCore } from "../../../../common/ragstudio/fake.js";
export { CORPUS };

export function createFake(corpus = CORPUS) {
  const kb = { knowledgeBaseId: "KBFAKE0001", name: "facilities-kb", status: "ACTIVE", updatedAt: new Date().toISOString() };
  const ds = { dataSourceId: "DSFAKE0001", name: "facilities-docs", status: "AVAILABLE" };
  let chunking = { chunkingStrategy: "FIXED_SIZE", fixedSizeChunkingConfiguration: { maxTokens: 48, overlapPercentage: 20 } };
  const core = createFakeCore(corpus, { chunkConfig: () => E.apiToDesign(chunking).chunk, kbId: kb.knowledgeBaseId });
  const api = {
    ...core, mode: "fake", label: "Demo corpus (in-browser fake)",
    async listKbs() { return [kb]; },
    async listCorpora() { return [kb]; },
    async getKb() { return kb; },
    async getDataSource() { return { ...ds, vectorIngestionConfiguration: { chunkingConfiguration: chunking } }; },
    async applyDesign(a) { chunking = a.dataSource.vectorIngestionConfiguration.chunkingConfiguration; kb.updatedAt = new Date().toISOString(); return { dataSourceId: ds.dataSourceId, chunkingConfiguration: chunking }; },
    async retrieve(query, o) { const tr = await api.trace(query, o); return { retrievalResults: tr.results.filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank).map((r) => ({ content: { type: "TEXT", text: r.text }, location: { type: "S3", s3Location: { uri: r.uri } }, metadata: r.metadata, score: r.rerank_score ?? r.vector_score })) }; },
    async rag(query, o) {
      const guard = E.piiScan(query).length || /\b(password|salary|home address)\b/i.test(query);
      if (guard) return { output: { text: "Sorry, the model cannot answer this question." }, citations: [], guardrailAction: "INTERVENED", guardrail: { input: E.piiScan(query).length ? "sensitive-information: PII in the question" : "denied topic" }, sessionId: "fake" };
      const tr = await api.trace(query, o), fin = tr.results.filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank);
      if (!fin.length || tr.confidence < o.threshold) return { output: { text: "I cannot answer that from the knowledge base: no sufficiently relevant source was found." }, citations: [], guardrailAction: "NONE", grounded: false, sessionId: "fake" };
      const q = E.contentTokens(query).map((x) => x.replace(/(ing|ed|es|s)$/, "")), picks = [];
      for (const r of fin.slice(0, 3)) for (const s of E.splitSentences(r.text)) { const st = new Set(E.contentTokens(s).map((x) => x.replace(/(ing|ed|es|s)$/, ""))), cov = q.filter((x) => st.has(x)).length / Math.max(1, q.length); if (cov > 0.3 && !picks.some((p) => p.s === s)) picks.push({ s, cov, r }); }
      picks.sort((a, b) => b.cov - a.cov); const use = picks.slice(0, 2);
      if (!use.length) return { output: { text: "I cannot answer that from the knowledge base: no sufficiently relevant source was found." }, citations: [], guardrailAction: "NONE", grounded: false, sessionId: "fake" };
      let text = "", cit = [];
      for (const p of use) { const start = text.length; text += (text ? " " : "") + p.s; cit.push({ generatedResponsePart: { textResponsePart: { text: p.s, span: { start, end: text.length } } }, retrievedReferences: [{ content: { text: p.r.text }, location: { type: "S3", s3Location: { uri: p.r.uri } }, metadata: p.r.metadata }] }); }
      return { output: { text }, citations: o.citations === false ? [] : cit, guardrailAction: "NONE", grounded: true, sessionId: "fake" };
    },
  };
  return api;
}
