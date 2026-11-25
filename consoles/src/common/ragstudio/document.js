/* vyomi.rag-design/v1: the cloud-neutral RAG design document.
 * Written by the RAG Studio export (any cloud console); read by course chapters' generated code.
 * toDocument(design, cloud, extra) / fromDocument(doc) convert between the Studio's internal design object (engine.js defaultDesign shape)
 * and the document; validate(doc) returns a list of problems (empty = valid). Pure functions, no DOM. */
import { defaultDesign, DEFAULT_GOLDEN } from "./engine.js";

export const SCHEMA = "vyomi.rag-design/v1";
export const CLOUDS = ["aws", "gcp", "azure"];
export const STRATEGIES = ["FIXED_SIZE", "SEMANTIC", "HIERARCHICAL", "NONE"];
export const SEARCH_TYPES = ["HYBRID", "SEMANTIC"];

const clone = (x) => JSON.parse(JSON.stringify(x));

export function toDocument(design, cloud, { golden = DEFAULT_GOLDEN, sources, createdAt = new Date().toISOString(), embeddingDimensions } = {}) {
  const d = design || defaultDesign();
  return {
    schema: SCHEMA,
    name: d.name,
    cloud,
    createdAt,
    chunking: { strategy: d.chunk.strategy, maxTokens: +d.chunk.maxTokens, overlapPct: +d.chunk.overlapPct },
    embedding: { model: d.embed.model, ...(embeddingDimensions ? { dimensions: +embeddingDimensions } : {}) },
    retrieve: {
      topK: +d.retrieve.topK, searchType: d.retrieve.searchType, hybridWeight: +d.retrieve.hybridWeight,
      filter: d.retrieve.filterKey ? { key: d.retrieve.filterKey, value: d.retrieve.filterValue } : null,
    },
    rerank: { enabled: !!d.rerank.enabled, topN: +d.rerank.topN },
    generate: { model: d.generate.model, citations: !!d.generate.citations, groundingThreshold: +d.generate.groundingThreshold, guardrailId: d.generate.guardrailId || "" },
    clean: { ...d.clean },
    store: d.index?.store || "",
    sources: sources || [{ bucket: d.source.bucket, prefix: d.source.prefix || "" }],
    golden: clone(golden),
  };
}

/** Document -> Studio design object (+ golden set). Missing optional fields fall back to defaultDesign(). */
export function fromDocument(doc) {
  const base = defaultDesign(), c = doc.chunking || {}, r = doc.retrieve || {}, rr = doc.rerank || {}, g = doc.generate || {};
  const src = (doc.sources && doc.sources[0]) || base.source;
  const design = {
    ...base, name: doc.name || base.name,
    source: { bucket: src.bucket ?? base.source.bucket, prefix: src.prefix || "" },
    clean: { ...base.clean, ...(doc.clean || {}) },
    chunk: { strategy: c.strategy ?? base.chunk.strategy, maxTokens: c.maxTokens ?? base.chunk.maxTokens, overlapPct: c.overlapPct ?? base.chunk.overlapPct },
    embed: { model: doc.embedding?.model ?? base.embed.model },
    index: { store: doc.store || base.index.store },
    retrieve: { searchType: r.searchType ?? base.retrieve.searchType, topK: r.topK ?? base.retrieve.topK, hybridWeight: r.hybridWeight ?? base.retrieve.hybridWeight,
      filterKey: r.filter?.key || "", filterValue: r.filter?.value || "" },
    rerank: { enabled: rr.enabled ?? base.rerank.enabled, topN: rr.topN ?? base.rerank.topN },
    generate: { ...base.generate, ...g },
  };
  return { design, golden: clone(doc.golden || []), cloud: doc.cloud, createdAt: doc.createdAt };
}

const isNum = (x) => typeof x === "number" && Number.isFinite(x);
/** Returns an array of "path: message" strings; [] when the document is valid. */
export function validate(doc) {
  const e = [], bad = (p, m) => e.push(`${p}: ${m}`);
  if (!doc || typeof doc !== "object") return ["document: not an object"];
  if (doc.schema !== SCHEMA) bad("schema", `must be "${SCHEMA}"`);
  if (!doc.name || typeof doc.name !== "string") bad("name", "required string");
  if (!CLOUDS.includes(doc.cloud)) bad("cloud", `one of ${CLOUDS.join(", ")}`);
  if (doc.createdAt && Number.isNaN(Date.parse(doc.createdAt))) bad("createdAt", "not an ISO date");
  const c = doc.chunking || {};
  if (!STRATEGIES.includes(c.strategy)) bad("chunking.strategy", `one of ${STRATEGIES.join(", ")}`);
  if (c.strategy !== "NONE") {
    if (!isNum(c.maxTokens) || c.maxTokens < 1) bad("chunking.maxTokens", "positive number");
    if (!isNum(c.overlapPct) || c.overlapPct < 0 || c.overlapPct > 99) bad("chunking.overlapPct", "0..99");
  }
  if (!doc.embedding?.model) bad("embedding.model", "required");
  if (doc.embedding?.dimensions != null && !(isNum(doc.embedding.dimensions) && doc.embedding.dimensions > 0)) bad("embedding.dimensions", "positive number");
  const r = doc.retrieve || {};
  if (!isNum(r.topK) || r.topK < 1) bad("retrieve.topK", "number >= 1");
  if (!SEARCH_TYPES.includes(r.searchType)) bad("retrieve.searchType", `one of ${SEARCH_TYPES.join(", ")}`);
  if (!isNum(r.hybridWeight) || r.hybridWeight < 0 || r.hybridWeight > 1) bad("retrieve.hybridWeight", "0..1 (vector share)");
  if (r.filter != null && !(r.filter.key && "value" in r.filter)) bad("retrieve.filter", "null or {key,value}");
  const rr = doc.rerank || {};
  if (typeof rr.enabled !== "boolean") bad("rerank.enabled", "boolean");
  else if (rr.enabled && (!isNum(rr.topN) || rr.topN < 1 || rr.topN >= r.topK)) bad("rerank.topN", "number >= 1 and less than retrieve.topK");
  const g = doc.generate || {};
  if (!isNum(g.groundingThreshold) || g.groundingThreshold < 0 || g.groundingThreshold > 1) bad("generate.groundingThreshold", "0..1");
  if (!Array.isArray(doc.sources) || !doc.sources.length) bad("sources", "non-empty array");
  if (!Array.isArray(doc.golden)) bad("golden", "array");
  else doc.golden.forEach((row, i) => { if (!row.question) bad(`golden[${i}].question`, "required"); if (!Array.isArray(row.expectedSources)) bad(`golden[${i}].expectedSources`, "array"); });
  return e;
}
