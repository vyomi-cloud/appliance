/* Azure-only: RAG design <-> Azure AI Search / Azure OpenAI request shapes (api-version 2023-11-01 index/indexer wire).
 *   chunking  -> SplitSkill textSplitMode "pages" + maximumPageLength (characters, ~4 per token) + pageOverlapLength
 *   embedding -> AzureOpenAIEmbeddingSkill + vector field `dimensions` + vectorSearch profile/vectorizer
 *   retrieve  -> docs/search: text (hybridWeight 0) | hybrid (search + vectorQueries, RRF) | vector (SEMANTIC design type)
 *   rerank    -> queryType "semantic" + a semantic configuration (title + chunk)
 * Honest gaps (surfaced in the UI via GAPS): SEMANTIC / HIERARCHICAL chunking have no Azure equivalent (pages only), semantic ranker
 * is an approximation, blob / cosmos / sql sources only, no OCR / image skills. */
import { EMBED_MODELS, defaultDesign } from "../../../../common/ragstudio/engine.js";

// Azure OpenAI embedding models, added to the shared model table so lint / the document accept them (additive; the AWS bundle never loads this file).
Object.assign(EMBED_MODELS, {
  "text-embedding-3-small": { label: "text-embedding-3-small (Azure OpenAI)", window: 8191, dims: 1536 },
  "text-embedding-3-large": { label: "text-embedding-3-large (Azure OpenAI)", window: 8191, dims: 3072 },
  "text-embedding-ada-002": { label: "text-embedding-ada-002 (Azure OpenAI)", window: 8191, dims: 1536 },
});

export const NAMES = { index: "ragstudio-chunks", parents: "ragstudio-parents", datasource: "ragstudio-ds", skillset: "ragstudio-skills", indexer: "ragstudio-indexer", semantic: "ragstudio-semantic", profile: "ragstudio-profile" };
export const CHARS_PER_TOKEN = 4;
export const MIN_PAGE = 300;
export const GAPS = [
  "Chunking: Azure AI Search splits by pages (SplitSkill). Semantic and hierarchical strategies are approximated by pages of the same size.",
  "Rerank: the semantic ranker is an approximation (embedding cosine + term coverage, 0 to 4 like the real one), not Microsoft's cross-encoder.",
  "Sources: only Blob Storage, Cosmos DB and Azure SQL data sources exist; no OCR, image or entity skills.",
  "Metadata filters work on the index's filterable fields (title = blob name, parent_id); blob user metadata is not projected.",
  "Vector search is an exact cosine scan (no HNSW graph); the embedding model is the local one, truncated or padded to the declared dimensions.",
];

export const defaultAzureDesign = () => {
  const d = defaultDesign();
  d.name = "facilities-search design";
  d.embed = { model: "text-embedding-3-small" };
  d.index = { store: "azure-ai-search" };
  d.chunk = { strategy: "FIXED_SIZE", maxTokens: 120, overlapPct: 15 };
  d.generate = { ...d.generate, model: "gpt-4o", guardrailId: "" };
  return d;
};

const pageLen = (c) => Math.max(MIN_PAGE, Math.round(+c.maxTokens * CHARS_PER_TOKEN));
const overlapLen = (c, ml) => Math.min(ml - 1, Math.round(ml * (+c.overlapPct) / 100));

/** Everything the Studio PUTs for a design. `env` = { storage:{account,key}, aoai:{account,embedDeployment,chatDeployment} }. */
export function designToAzure(d, env = {}) {
  const dims = EMBED_MODELS[d.embed.model]?.dims || 1536, none = d.chunk.strategy === "NONE";
  const ml = none ? 100000 : pageLen(d.chunk), ov = none ? 0 : overlapLen(d.chunk, ml);
  const res = { resourceUri: `https://${env.aoai?.account || "aoai"}.openai.azure.com`, deploymentId: env.aoai?.embedDeployment || "embed", modelName: d.embed.model };
  const vectorSearch = { algorithms: [{ name: "hnsw1", kind: "hnsw" }], vectorizers: [{ name: "aoai", kind: "azureOpenAI", azureOpenAIParameters: res }], profiles: [{ name: NAMES.profile, algorithm: "hnsw1", vectorizer: "aoai" }] };
  const index = {
    name: NAMES.index,
    fields: [{ name: "chunk_id", type: "Edm.String", key: true }, { name: "parent_id", type: "Edm.String", filterable: true },
      { name: "title", type: "Edm.String", searchable: true, filterable: true, retrievable: true }, { name: "chunk", type: "Edm.String", searchable: true },
      { name: "text_vector", type: "Collection(Edm.Single)", dimensions: dims, vectorSearchProfile: NAMES.profile }],
    vectorSearch,
    semantic: { defaultConfiguration: NAMES.semantic, configurations: [{ name: NAMES.semantic, prioritizedFields: { titleField: { fieldName: "title" }, prioritizedContentFields: [{ fieldName: "chunk" }] } }] },
  };
  const parents = { name: NAMES.parents, fields: [{ name: "doc_id", type: "Edm.String", key: true }, { name: "metadata_storage_name", type: "Edm.String", searchable: true }] };
  const skillset = { name: NAMES.skillset, description: `RAG Studio: ${d.name}`, skills: [
    { "@odata.type": "#Microsoft.Skills.Text.SplitSkill", name: "split", textSplitMode: "pages", maximumPageLength: ml, pageOverlapLength: ov, context: "/document",
      inputs: [{ name: "text", source: "/document/content" }], outputs: [{ name: "textItems", targetName: "pages" }] },
    { "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill", name: "embed", context: "/document/pages/*", ...res, dimensions: dims,
      inputs: [{ name: "text", source: "/document/pages/*" }], outputs: [{ name: "embedding", targetName: "text_vector" }] }],
    indexProjections: { selectors: [{ targetIndexName: NAMES.index, parentKeyFieldName: "parent_id", sourceContext: "/document/pages/*",
      mappings: [{ name: "chunk", source: "/document/pages/*" }, { name: "text_vector", source: "/document/pages/*/text_vector" }, { name: "title", source: "/document/metadata_storage_name" }] }],
      parameters: { projectionMode: "skipIndexingParentDocuments" } } };
  const acct = env.storage?.account || "storageaccount";
  const datasource = { name: NAMES.datasource, type: "azureblob", credentials: { connectionString: `DefaultEndpointsProtocol=https;AccountName=${acct};AccountKey=${env.storage?.key || "x"}` },
    container: { name: d.source.bucket, ...(d.source.prefix ? { query: d.source.prefix } : {}) } };
  const indexer = { name: NAMES.indexer, dataSourceName: NAMES.datasource, targetIndexName: NAMES.parents, skillsetName: NAMES.skillset, parameters: { configuration: { parsingMode: "text" } } };
  return { index, parents, skillset, datasource, indexer, dims, notes: d.chunk.strategy === "SEMANTIC" || d.chunk.strategy === "HIERARCHICAL" ? [`${d.chunk.strategy} chunking is approximated by pages`] : [] };
}

/** SplitSkill -> design.chunk (inverse of the chunking half of designToAzure). */
export function azureToChunk(skillset, base = defaultAzureDesign().chunk) {
  const s = (skillset?.skills || []).find((x) => /SplitSkill$/.test(x["@odata.type"] || ""));
  if (!s) return { strategy: "NONE", maxTokens: base.maxTokens, overlapPct: base.overlapPct };
  const ml = s.maximumPageLength || 5000;
  if (ml >= 100000) return { strategy: "NONE", maxTokens: base.maxTokens, overlapPct: base.overlapPct };
  return { strategy: "FIXED_SIZE", maxTokens: Math.round(ml / CHARS_PER_TOKEN), overlapPct: Math.round(((s.pageOverlapLength || 0) / ml) * 100) };
}

/** The retrieval mode a design runs as: text (vector share 0), vector (design type SEMANTIC), hybrid (RRF), each optionally semantic-reranked. */
export const modeOf = (o) => (o.searchType === "SEMANTIC" || o.hybridWeight >= 1 ? "vector" : o.hybridWeight <= 0 ? "text" : "hybrid");

/** One retrieval request body (docs/search) for the retrieval options of a design (engine.retrievalOptions). */
export function queryBody(q, o) {
  const mode = modeOf(o), top = +o.numberOfResults;
  const body = { search: mode === "vector" && !o.rerank ? "*" : q, top, count: true };   // the semantic ranker needs a text query
  if (mode !== "text") {
    const w = mode === "vector" ? 1 : o.hybridWeight;
    body.vectorQueries = [{ kind: "text", text: q, fields: "text_vector", k: Math.max(50, top), weight: mode === "vector" ? 1 : +(w / (1 - w)).toFixed(3) }];
  }
  if (o.rerank) { body.queryType = "semantic"; body.semanticConfiguration = NAMES.semantic; }
  if (o.filter) body.filter = `${o.filter.key} eq '${String(o.filter.value).replace(/'/g, "''")}'`;
  return body;
}

/** Chat "on your data" body for the Azure OpenAI ARM proxy. */
export function chatBody(q, o, { endpoint, key, threshold }) {
  const qt = o.searchType === "SEMANTIC" ? (o.rerank ? "vector_semantic_hybrid" : "vector") : o.hybridWeight > 0 ? (o.rerank ? "vector_semantic_hybrid" : "vector_simple_hybrid") : o.rerank ? "semantic" : "simple";
  return { messages: [{ role: "user", content: q }], temperature: 0.1, max_tokens: 400,
    data_sources: [{ type: "azure_search", parameters: { endpoint, index_name: NAMES.index, authentication: { type: "api_key", key }, top_n_documents: o.rerank ? +o.rerankTopN : +o.numberOfResults,
      query_type: qt, in_scope: true, strictness: threshold >= 0.5 ? 4 : 3, ...(o.rerank ? { semantic_configuration: NAMES.semantic } : {}), ...(o.filter ? { filter: `${o.filter.key} eq '${o.filter.value}'` } : {}),
      fields_mapping: { content_fields: ["chunk"], title_field: "title", vector_fields: ["text_vector"] } } }] };
}
