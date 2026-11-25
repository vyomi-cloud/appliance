/* RAG Studio cloud adapter interface. Each cloud console implements this and passes it to the Studio UI.
 * AWS: consoles/src/aws/services/bedrock/studio/backend.js (live) + fake.js (demo). GCP / Azure follow the same shapes.
 *
 * @typedef {"live"|"live-limited"|"fake"} AdapterMode
 *   live         real cloud wires AND the Vyomi inspect extension (chunks + per-stage trace)
 *   live-limited real wires work (apply/ingest/retrieve/rag) but no inspect API: corpus and stage-score views are limited
 *   fake         in-browser demo corpus (common/ragstudio/fake.js), identical shapes
 *
 * @typedef {Object} Chunk        { id, uri, text, tokens, metadata, pii:string[], lang, embedding:number[]|undefined, position:[x,y]|undefined }
 * @typedef {Object} RetrieveOptions  from engine.retrievalOptions(design): { numberOfResults, searchType, hybridWeight, rerank, rerankTopN, filter:{key,value}|null, threshold }
 * @typedef {Object} TraceRow     { id, uri, text, tokens, metadata, vector_score, vector_rank, bm25_score, bm25_rank, fused_rank, rerank_score, filtered_out_reason, final_rank }
 *
 * @typedef {Object} RagAdapter
 * @property {AdapterMode} mode
 * @property {string} label                                  shown in the Studio header
 * @property {() => Promise<Array>} listCorpora              knowledge bases / datastores / indexes the studio can target
 * @property {(apiDesign:Object) => Promise<Object>} applyDesign   push the cloud-specific form of the design (cloud-side designToApi output); UpdateDataSource-equivalent
 * @property {() => Promise<Object>} ingest                  start + await ingestion; resolves the finished job { status, statistics }
 * @property {() => Promise<{embeddingModel:string, chunks:Chunk[]}>} chunks   inspect API; throws when mode is live-limited
 * @property {(query:string, o:RetrieveOptions) => Promise<{query, options, queryEmbedding:number[]|null, results:TraceRow[], latencyMs:Object, confidence:number}>} trace
 * @property {(query:string, o:RetrieveOptions) => Promise<{retrievalResults:Array}>} retrieve   cloud-native shape of the retrieval call
 * @property {(query:string, o:RetrieveOptions) => Promise<{output:{text:string}, citations:Array, guardrailAction:string}>} rag   retrieve-and-generate
 *
 * The cloud-specific design mapping (chunking/retrieval/rerank request shapes) stays in the cloud folder
 * (AWS: bedrockMap.js designToApi / apiToDesign); the document format (document.js) is the neutral exchange format. */

export const ADAPTER_METHODS = ["listCorpora", "applyDesign", "ingest", "chunks", "trace", "retrieve", "rag"];
export const ADAPTER_MODES = ["live", "live-limited", "fake"];

/** Returns missing/invalid members of an adapter ([] = conforms). */
export function checkAdapter(a) {
  const e = [];
  if (!a || typeof a !== "object") return ["adapter: not an object"];
  if (!ADAPTER_MODES.includes(a.mode)) e.push(`mode: one of ${ADAPTER_MODES.join(", ")}`);
  if (typeof a.label !== "string") e.push("label: string");
  for (const m of ADAPTER_METHODS) if (typeof a[m] !== "function") e.push(`${m}: function`);
  return e;
}
