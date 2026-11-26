/* GCP-only: RAG design <-> Vertex AI RAG Engine request shapes (ragFileTransformationConfig, ragRetrievalConfig, ragEmbeddingModelConfig).
 * The cloud-neutral document (common/ragstudio/document.js) stays free of these shapes, like AWS bedrockMap.js. */
import { EMBED_MODELS, defaultDesign } from "../../../../common/ragstudio/engine.js";

// GCP names the embedding models text-embedding-*; the simulator resolves them to the local embedder. Registered here so the shared lint knows their window.
EMBED_MODELS["text-embedding-005"] = { label: "text-embedding-005 (local embedder)", window: 2048, dims: 768 };
EMBED_MODELS["text-embedding-004"] = { label: "text-embedding-004 (local embedder)", window: 2048, dims: 768 };
EMBED_MODELS["gemini-embedding-001"] = { label: "gemini-embedding-001 (local embedder)", window: 2048, dims: 768 };

export const CHARS_PER_TOKEN = 5;   // core/gcp_agentplatform_core._make_file chunks at chunkSize // 5 tokens
export const RERANK_MODEL = "semantic-ranker-default-004";
export const GCP_DEFAULTS = { name: "facilities-corpus design", embed: { model: "text-embedding-005" }, index: { store: "rag-managed-db" }, generate: { model: "gemini-2.0-flash", citations: true, groundingThreshold: 0.25, guardrailId: "" }, source: { bucket: "facilities-docs", prefix: "" } };
export const gcpDefaultDesign = () => { const d = defaultDesign(); return { ...d, ...GCP_DEFAULTS, source: { ...GCP_DEFAULTS.source }, embed: { ...GCP_DEFAULTS.embed }, index: { ...GCP_DEFAULTS.index }, generate: { ...d.generate, ...GCP_DEFAULTS.generate } }; };

/** Design -> Vertex AI shapes. `transformation` rides on ragFiles:upload / ragFiles:import; `ragRetrievalConfig` on :retrieveContexts. */
export function designToApi(d) {
  const c = d.chunk, notes = [];
  if (c.strategy !== "FIXED_SIZE") notes.push(`${c.strategy} chunking is not offered by the RAG Engine: it is applied as fixed-length chunking.`);
  const chunkSize = Math.max(16, Math.round(+c.maxTokens * CHARS_PER_TOKEN));
  const chunkOverlap = c.strategy === "NONE" ? 0 : Math.min(chunkSize - 1, Math.round(chunkSize * (+c.overlapPct) / 100));
  const transformation = { ragFileChunkingConfig: { fixedLengthChunking: { chunkSize, chunkOverlap } } };
  const r = d.retrieve, ragRetrievalConfig = { topK: d.rerank.enabled ? +d.rerank.topN : +r.topK };
  if (r.searchType !== "SEMANTIC") ragRetrievalConfig.hybridSearch = { alpha: +r.hybridWeight };
  if (d.rerank.enabled) ragRetrievalConfig.ranking = { rankService: { modelName: RERANK_MODEL } };
  return {
    transformation, notes,
    importRagFilesConfig: { gcsSource: { uris: [`gs://${d.source.bucket}${d.source.prefix ? "/" + d.source.prefix.replace(/^\//, "") : ""}`] }, ragFileTransformationConfig: transformation },
    ragRetrievalConfig,
    ragEmbeddingModelConfig: { vertexPredictionEndpoint: { model: `publishers/google/models/${d.embed.model}` } },
  };
}
export function apiToDesign(transformation, base = gcpDefaultDesign()) {
  const d = JSON.parse(JSON.stringify(base)), f = transformation?.ragFileChunkingConfig?.fixedLengthChunking;
  if (f) d.chunk = { strategy: "FIXED_SIZE", maxTokens: Math.round(f.chunkSize / CHARS_PER_TOKEN), overlapPct: Math.round((f.chunkOverlap / f.chunkSize) * 100) };
  return d;
}

/** Retrieval options (engine.retrievalOptions) -> ragRetrievalConfig. `fileIds` resolves a {key:file|source,value} filter to ragFileIds. */
export function toRagRetrievalConfig(o) {
  const c = { topK: o.rerank ? o.rerankTopN : o.numberOfResults };
  if (o.searchType !== "SEMANTIC") c.hybridSearch = { alpha: o.hybridWeight };
  if (o.rerank) c.ranking = { rankService: { modelName: RERANK_MODEL } };
  return c;
}

/** GCP-specific lint findings added to the shared lintDesign output. */
export function gcpLint(d) {
  const out = [], add = (id, severity, node, message) => out.push({ id, severity, node, message });
  if (d.chunk.strategy !== "FIXED_SIZE") add("gcp-fixed-only", "warning", "chunk", `Vertex AI RAG Engine chunks with fixedLengthChunking only (size + overlap); ${d.chunk.strategy} will be applied as FIXED_SIZE.`);
  if (d.retrieve.filterKey && !["file", "source"].includes(d.retrieve.filterKey)) add("gcp-filter-key", "warning", "retrieve", `The RAG Engine filters by file (ragFileIds): use metadata key "file" or "source", not "${d.retrieve.filterKey}".`);
  if (d.rerank.enabled) add("gcp-rerank-pool", "info", "rerank", `Rerank is a ranking.rankService config: the engine reranks the top ${3 * (+d.rerank.topN || 0)} fused candidates (3 x topN) down to topN.`);
  if (d.embed.model && !/embedding/.test(d.embed.model)) add("gcp-embed-model", "error", "embed", `"${d.embed.model}" is not an embedding model; the corpus embedding model must be a text-embedding-* publisher model.`);
  return out;
}

/** retrieve-trace response -> the Studio's TraceRow list. chunkMap: id -> chunk from the inspect chunks call. */
export function traceRows(trace, o, chunkMap, finalIds) {
  const cand = trace.candidates || [], pool = o.rerank ? o.numberOfResults : o.numberOfResults;
  const keep = cand.filter((c) => c.returned || (c.fused_rank && c.fused_rank <= pool));
  const dropped = cand.filter((c) => c.filtered_out_reason === "excluded by ragFileIds filter").slice(0, 3);
  return [...keep, ...dropped].map((c) => {
    const ch = chunkMap.get(c.chunkId) || {}, fin = finalIds.indexOf(c.chunkId);
    return { id: c.chunkId, uri: ch.uri || c.uri, text: ch.text || "", tokens: ch.tokens || 0, metadata: ch.metadata || {},
      vector_score: c.vector_score, vector_rank: c.vector_rank, bm25_score: c.bm25_score, bm25_rank: c.bm25_rank, fused_rank: c.fused_rank,
      rerank_score: c.rerank_score, filtered_out_reason: c.returned ? null : (c.filtered_out_reason && !/^below top-k|rerank/.test(c.filtered_out_reason) ? c.filtered_out_reason : null),
      final_rank: fin >= 0 ? fin + 1 : null };
  });
}

/** Studio filter {key:file|source,value} -> ragFileIds of the corpus files it matches. */
export function fileIdsFor(filter, chunks) {
  if (!filter) return null;
  if (!["file", "source"].includes(filter.key)) throw Object.assign(new Error(`The RAG Engine filters by file only: metadata key "file" or "source", not "${filter.key}".`), { code: "INVALID_ARGUMENT", status: 400 });
  const ids = new Set();
  for (const c of chunks) if (String(c.metadata?.[filter.key]) === String(filter.value) || String(c.uri).includes(filter.value)) ids.add(String(c.id).split("-")[0]);
  return [...ids];
}

/** retrieve-trace / retrieveContexts request body for the studio options. */
export const retrieveBody = (corpus, query, o, fileIds) => ({ query: { text: query, ragRetrievalConfig: toRagRetrievalConfig(o) },
  vertexRagStore: { ragResources: [{ ragCorpus: corpus.name, ...(fileIds ? { ragFileIds: fileIds } : {}) }] } });

/** generateContent groundingMetadata -> Studio citations ([{generatedResponsePart, retrievedReferences:[{content,location:{uri}}]}]). */
export function citationsFrom(gm) {
  if (!gm) return [];
  const chunks = gm.groundingChunks || [];
  const ref = (i) => { const c = chunks[i]?.retrievedContext || {}; return { content: { text: c.text || "" }, location: { uri: /^gs:\/\//.test(c.uri || "") ? c.uri : (c.title || c.uri || "") }, metadata: { title: c.title } }; };
  return (gm.groundingSupports || []).map((s) => ({ generatedResponsePart: { textResponsePart: { text: s.segment?.text || "" } }, retrievedReferences: (s.groundingChunkIndices || []).map(ref) }));
}

