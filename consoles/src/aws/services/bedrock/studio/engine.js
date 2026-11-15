/* RAG Studio engine: pure functions only (no DOM, no wire) so they run in the browser, on Nano and in node tests.
 * Deterministic metrics, design linter, design<->Bedrock API mapping, chunker, BM25, hashing embedder (used by the in-browser fake). */

export const STOP = new Set("a an the of to in on for and or is are was were be by with at as it its this that these those from into than then if not no do does did can may must should will shall per each any all your you we our their his her them they who whom which what when where how why about over under after before between during up down out off".split(" "));
export const tokenize = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9À-ɏ]+/g, " ").trim().split(/\s+/).filter(Boolean);
export const contentTokens = (s) => tokenize(s).filter((t) => !STOP.has(t) && t.length > 1);
const stem = (t) => t.replace(/(ing|ed|es|s)$/, "");
export const countTokens = (text) => Math.ceil(tokenize(text).length * 1.33);
export const splitSentences = (t) => String(t || "").replace(/\s+/g, " ").match(/[^.!?]+[.!?]*(\s+|$)/g)?.map((s) => s.trim()).filter(Boolean) || [];

// ── models (context windows in tokens) ──
export const EMBED_MODELS = {
  "amazon.titan-embed-text-v2:0": { label: "Titan Text Embeddings V2", window: 8192, dims: 1024 },
  "vyomi.nomic-embed-text": { label: "Nomic Embed Text (local)", window: 2048, dims: 768 },
  "vyomi.minilm-l6": { label: "MiniLM L6 (local, small)", window: 256, dims: 384 },
};

// ── design model ──
export const defaultDesign = () => ({
  name: "facilities-kb design", version: 1,
  source: { bucket: "facilities-docs", prefix: "" },
  parse: { parser: "text" },
  clean: { piiScan: true, stripHtml: true, dedupe: true },
  chunk: { strategy: "FIXED_SIZE", maxTokens: 48, overlapPct: 20 },
  embed: { model: "vyomi.nomic-embed-text" },
  index: { store: "pgvector" },
  retrieve: { searchType: "HYBRID", topK: 12, hybridWeight: 0.6, filterKey: "", filterValue: "" },
  rerank: { enabled: true, topN: 4 },
  generate: { model: "vyomi.qwen2.5-3b", citations: true, groundingThreshold: 0.25, guardrailId: "facilities-guardrail" },
});

export const PRESETS = {
  "policy-manuals": { label: "Policy manuals", note: "Long structured prose: larger semantic chunks, hybrid search, rerank.",
    patch: { chunk: { strategy: "SEMANTIC", maxTokens: 300, overlapPct: 15 }, retrieve: { searchType: "HYBRID", topK: 12, hybridWeight: 0.55 }, rerank: { enabled: true, topN: 4 }, generate: { groundingThreshold: 0.3 } } },
  "maintenance-logs": { label: "Maintenance logs", note: "Short terse entries: small chunks, keyword-heavy (BM25 weighted), no rerank.",
    patch: { chunk: { strategy: "FIXED_SIZE", maxTokens: 80, overlapPct: 10 }, retrieve: { searchType: "HYBRID", topK: 8, hybridWeight: 0.3 }, rerank: { enabled: false, topN: 4 }, generate: { groundingThreshold: 0.2 } } },
  "semantic-only": { label: "Semantic only", note: "Vector search only; baseline to compare against hybrid.",
    patch: { retrieve: { searchType: "SEMANTIC", topK: 8, hybridWeight: 1 }, rerank: { enabled: false, topN: 4 } } },
};
export function applyPreset(design, key) {
  const p = PRESETS[key]; if (!p) return design;
  const d = JSON.parse(JSON.stringify(design));
  for (const [k, v] of Object.entries(p.patch)) d[k] = { ...d[k], ...v };
  d.name = `${PRESETS[key].label} preset`;
  return d;
}

/** Design -> the real Bedrock shapes. chunkingConfiguration goes to Create/UpdateDataSource; retrievalConfiguration rides on every Retrieve/RetrieveAndGenerate. */
export function designToApi(d) {
  const c = d.chunk;
  const chunkingConfiguration = c.strategy === "NONE" ? { chunkingStrategy: "NONE" }
    : c.strategy === "SEMANTIC" ? { chunkingStrategy: "SEMANTIC", semanticChunkingConfiguration: { maxTokens: +c.maxTokens, bufferSize: 1, breakpointPercentileThreshold: 95 } }
    : c.strategy === "HIERARCHICAL" ? { chunkingStrategy: "HIERARCHICAL", hierarchicalChunkingConfiguration: { levelConfigurations: [{ maxTokens: +c.maxTokens * 3 }, { maxTokens: +c.maxTokens }], overlapTokens: Math.round(+c.maxTokens * c.overlapPct / 100) } }
    : { chunkingStrategy: "FIXED_SIZE", fixedSizeChunkingConfiguration: { maxTokens: +c.maxTokens, overlapPercentage: +c.overlapPct } };
  const r = d.retrieve;
  const vectorSearchConfiguration = { numberOfResults: +r.topK, overrideSearchType: r.searchType === "SEMANTIC" ? "SEMANTIC" : "HYBRID" };
  if (r.filterKey) vectorSearchConfiguration.filter = { equals: { key: r.filterKey, value: r.filterValue } };
  if (d.rerank.enabled) vectorSearchConfiguration.rerankingConfiguration = { type: "BEDROCK_RERANKING_MODEL", bedrockRerankingConfiguration: { modelConfiguration: { modelArn: "arn:aws:bedrock:us-east-1::foundation-model/amazon.rerank-v1:0" }, numberOfRerankedResults: +d.rerank.topN } };
  return {
    dataSource: { vectorIngestionConfiguration: { chunkingConfiguration }, dataSourceConfiguration: { type: "S3", s3Configuration: { bucketArn: `arn:aws:s3:::${d.source.bucket}`, ...(d.source.prefix ? { inclusionPrefixes: [d.source.prefix] } : {}) } } },
    retrievalConfiguration: { vectorSearchConfiguration },
  };
}
export function apiToDesign(chunkingConfiguration, base = defaultDesign()) {
  const d = JSON.parse(JSON.stringify(base)), c = chunkingConfiguration || {};
  const f = c.fixedSizeChunkingConfiguration, s = c.semanticChunkingConfiguration, h = c.hierarchicalChunkingConfiguration;
  if (c.chunkingStrategy === "NONE") d.chunk.strategy = "NONE";
  else if (s) d.chunk = { strategy: "SEMANTIC", maxTokens: s.maxTokens, overlapPct: d.chunk.overlapPct };
  else if (h) d.chunk = { strategy: "HIERARCHICAL", maxTokens: h.levelConfigurations?.[1]?.maxTokens || 200, overlapPct: 20 };
  else if (f) d.chunk = { strategy: "FIXED_SIZE", maxTokens: f.maxTokens, overlapPct: f.overlapPercentage };
  return d;
}
/** The retrieval options one query runs with (what the fake / inspect API accept). */
export const retrievalOptions = (d) => ({ numberOfResults: +d.retrieve.topK, searchType: d.retrieve.searchType, hybridWeight: d.retrieve.searchType === "SEMANTIC" ? 1 : +d.retrieve.hybridWeight, rerank: !!d.rerank.enabled, rerankTopN: +d.rerank.topN, filter: d.retrieve.filterKey ? { key: d.retrieve.filterKey, value: d.retrieve.filterValue } : null, threshold: +d.generate.groundingThreshold });

// ── static lint ──
/** ctx: { chunks?: [{uri,metadata,tokens}] } optional corpus facts. Returns [{id, severity: error|warning|info, node, message, fix?:{path,value}}]. */
export function lintDesign(d, ctx = {}) {
  const out = [], add = (id, severity, node, message, fix) => out.push({ id, severity, node, message, ...(fix ? { fix } : {}) });
  const win = EMBED_MODELS[d.embed.model]?.window;
  if (!win) add("embed-unknown", "warning", "embed", `Unknown embedding model "${d.embed.model}": window and dimensions cannot be checked.`);
  if (win && d.chunk.strategy !== "NONE" && +d.chunk.maxTokens > win) add("chunk-over-window", "error", "chunk", `Chunk size ${d.chunk.maxTokens} tokens exceeds the ${win}-token window of ${EMBED_MODELS[d.embed.model].label}; the tail of every chunk is truncated before embedding.`, { path: "chunk.maxTokens", value: win });
  if (win && d.chunk.strategy === "NONE" && ctx.chunks?.some((c) => c.tokens > win)) add("none-over-window", "error", "chunk", `Strategy NONE keeps whole documents, and some exceed the ${win}-token embedding window.`);
  if (d.chunk.strategy !== "NONE" && +d.chunk.maxTokens > 512 && (ctx.avgDocTokens || 1e9) > 1500 && +d.chunk.overlapPct === 0) add("no-overlap-long", "warning", "chunk", "No overlap on long documents: facts spanning a chunk boundary are lost.", { path: "chunk.overlapPct", value: 15 });
  if (d.chunk.strategy === "FIXED_SIZE" && +d.chunk.overlapPct === 0 && +d.chunk.maxTokens >= 200) add("no-overlap", "warning", "chunk", "Fixed-size chunks with 0% overlap cut sentences at arbitrary points; use 10-20% overlap.", { path: "chunk.overlapPct", value: 15 });
  if (+d.chunk.overlapPct > 50) add("overlap-high", "warning", "chunk", `Overlap ${d.chunk.overlapPct}% duplicates most of every chunk; index size and near-duplicate hits balloon.`, { path: "chunk.overlapPct", value: 20 });
  if (d.chunk.strategy !== "NONE" && +d.chunk.maxTokens < 40) add("chunk-tiny", "warning", "chunk", "Chunks under 40 tokens carry too little context to answer from.", { path: "chunk.maxTokens", value: 100 });
  if (d.rerank.enabled && +d.rerank.topN >= +d.retrieve.topK) add("rerank-no-headroom", "error", "rerank", `Rerank returns top ${d.rerank.topN} of only ${d.retrieve.topK} candidates: it can reorder but never promote a better chunk. Retrieve at least 2x the rerank size.`, { path: "retrieve.topK", value: +d.rerank.topN * 3 });
  if (!d.rerank.enabled && +d.retrieve.topK > 8) add("topk-large-no-rerank", "info", "rerank", `Top-k ${d.retrieve.topK} without reranking sends many low-precision chunks to the model; enable rerank or lower top-k.`);
  if (d.retrieve.searchType === "HYBRID" && (+d.retrieve.hybridWeight <= 0 || +d.retrieve.hybridWeight >= 1)) add("hybrid-degenerate", "warning", "retrieve", `Hybrid weight ${d.retrieve.hybridWeight} makes hybrid search equal to a single retriever; use 0.2-0.8.`, { path: "retrieve.hybridWeight", value: 0.5 });
  if (+d.retrieve.topK < 1) add("topk-zero", "error", "retrieve", "Top-k must be at least 1.", { path: "retrieve.topK", value: 5 });
  if (d.retrieve.filterKey && !d.retrieve.filterValue) add("filter-empty-value", "error", "retrieve", `Metadata filter on "${d.retrieve.filterKey}" has no value.`);
  if (d.retrieve.filterKey && ctx.chunks?.length) {
    const hit = ctx.chunks.filter((c) => String(c.metadata?.[d.retrieve.filterKey]) === String(d.retrieve.filterValue)).length;
    const keyKnown = ctx.chunks.some((c) => d.retrieve.filterKey in (c.metadata || {}));
    if (!keyKnown) add("filter-unknown-key", "error", "retrieve", `No chunk carries metadata key "${d.retrieve.filterKey}": the filter matches nothing.`);
    else if (!hit) add("filter-no-match", "error", "retrieve", `Filter ${d.retrieve.filterKey} = "${d.retrieve.filterValue}" matches 0 of ${ctx.chunks.length} chunks.`);
    else if (hit < +d.retrieve.topK) add("filter-narrow", "info", "retrieve", `Filter matches only ${hit} chunks, fewer than top-k ${d.retrieve.topK}.`);
  }
  if (+d.generate.groundingThreshold > 0.8) add("grounding-strict", "warning", "generate", "A grounding threshold above 0.8 will refuse most questions.", { path: "generate.groundingThreshold", value: 0.4 });
  if (+d.generate.groundingThreshold === 0) add("grounding-off", "warning", "generate", "Grounding threshold 0: the model answers even when nothing relevant was retrieved (hallucination risk).", { path: "generate.groundingThreshold", value: 0.25 });
  if (!d.generate.citations) add("citations-off", "warning", "generate", "Citations are off: answers cannot be audited against sources (C12 requires cited answers).", { path: "generate.citations", value: true });
  if (!d.generate.guardrailId) add("no-guardrail", "warning", "generate", "No guardrail attached to generation.");
  if (!d.clean.piiScan && ctx.chunks?.some((c) => c.pii?.length)) add("pii-unscanned", "error", "clean", "The corpus contains PII but the PII scan is off: it will be embedded and retrievable.", { path: "clean.piiScan", value: true });
  if (!d.clean.dedupe && ctx.dupClusters > 0) add("dupes-kept", "info", "clean", `${ctx.dupClusters} duplicate/near-duplicate cluster(s) exist and de-duplication is off.`, { path: "clean.dedupe", value: true });
  return out;
}
export function applyFix(d, fix) {
  const x = JSON.parse(JSON.stringify(d)), parts = fix.path.split(".");
  let o = x; for (const p of parts.slice(0, -1)) o = o[p];
  o[parts[parts.length - 1]] = fix.value; return x;
}

// ── chunking (the fake backend and the corpus "what-if" use it; the real backend chunks server-side) ──
export function chunkText(text, { strategy = "FIXED_SIZE", maxTokens = 200, overlapPct = 20 } = {}) {
  const t = String(text || "").trim(); if (!t) return [];
  if (strategy === "NONE") return [{ text: t }];
  const budget = Math.max(8, Math.floor(maxTokens / 1.33));
  if (strategy === "FIXED_SIZE" || strategy === "HIERARCHICAL") {
    const w = t.split(/\s+/), step = Math.max(1, Math.round(budget * (1 - overlapPct / 100))), out = [];
    for (let i = 0; i < w.length; i += step) { out.push({ text: w.slice(i, i + budget).join(" ") }); if (i + budget >= w.length) break; }
    return out;
  }
  // SEMANTIC: pack whole sentences, break early where the lexical overlap with the running chunk collapses (topic shift)
  const sents = splitSentences(t), out = []; let cur = [], len = 0;
  const flush = () => { if (cur.length) out.push({ text: cur.join(" ") }); const keep = overlapPct > 0 ? cur.slice(-1) : []; cur = keep.slice(); len = cur.join(" ").split(/\s+/).filter(Boolean).length; };
  for (const s of sents) {
    const n = s.split(/\s+/).length;
    const a = new Set(contentTokens(cur.join(" "))), b = contentTokens(s);
    const sim = b.length ? b.filter((x) => a.has(x)).length / b.length : 1;
    if (cur.length >= 2 && (len + n > budget || (len > budget * 0.5 && sim < 0.05))) flush();
    cur.push(s); len += n;
  }
  if (cur.length && !(out.length && cur.length === 1 && overlapPct > 0 && out[out.length - 1].text.endsWith(cur[0]))) out.push({ text: cur.join(" ") });
  return out;
}

// ── retrieval primitives ──
export function bm25Index(docs) { // docs: [{id,text}]
  const N = docs.length, df = new Map(), tf = new Map(); let total = 0;
  for (const d of docs) { const toks = tokenize(d.text).map(stem), m = new Map(); toks.forEach((t) => m.set(t, (m.get(t) || 0) + 1)); tf.set(d.id, { m, len: toks.length }); total += toks.length; new Set(toks).forEach((t) => df.set(t, (df.get(t) || 0) + 1)); }
  const avg = total / Math.max(1, N);
  return { score(query, id) { const e = tf.get(id); if (!e) return 0; let s = 0; for (const q of new Set(contentTokens(query).map(stem))) { const f = e.m.get(q) || 0; if (!f) continue; const idf = Math.log(1 + (N - (df.get(q) || 0) + 0.5) / ((df.get(q) || 0) + 0.5)); s += idf * (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * e.len / avg)); } return s; } };
}
export function hashEmbed(text, dim = 256) {
  const v = new Float32Array(dim), add = (k, w) => { let h = 2166136261; for (let i = 0; i < k.length; i++) { h ^= k.charCodeAt(i); h = Math.imul(h, 16777619); } v[(h >>> 0) % dim] += ((h >>> 8) & 1 ? 1 : -1) * w; };
  const toks = contentTokens(text).map(stem);
  for (const t of toks) { add("w:" + t, 1); for (let i = 0; i + 3 <= t.length; i++) add("c:" + t.slice(i, i + 3), 0.35); }
  for (let i = 0; i + 1 < toks.length; i++) add("b:" + toks[i] + "_" + toks[i + 1], 0.5);
  let n = 0; for (const x of v) n += x * x; n = Math.sqrt(n) || 1; return Array.from(v, (x) => +(x / n).toFixed(5));
}
export const cosine = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };

/** Weighted reciprocal-rank fusion. w = vector weight. */
export const fuse = (rv, rb, w, k = 60) => w / (k + rv) + (1 - w) / (k + rb);

/** Query-aware rerank score in 0..1 (stand-in cross-encoder for the fake: term coverage + adjacent-pair + doc-title match). */
export function rerankScore(query, chunk) {
  const q = contentTokens(query).map(stem), c = new Set(contentTokens(chunk.text).map(stem)), ct = contentTokens(chunk.text).map(stem);
  if (!q.length) return 0;
  const cov = q.filter((t) => c.has(t)).length / q.length;
  let pairs = 0; for (let i = 0; i + 1 < q.length; i++) for (let j = 0; j + 1 < ct.length; j++) if (q[i] === ct[j] && q[i + 1] === ct[j + 1]) { pairs++; break; }
  const title = new Set(tokenize(chunk.uri).map(stem)), tb = q.some((t) => title.has(t)) ? 0.08 : 0;
  return Math.min(1, 0.75 * cov + 0.25 * (pairs / Math.max(1, q.length - 1)) + tb);
}

// ── corpus analytics (pre-RAG) ──
export function histogram(values, bins = 10) {
  if (!values.length) return [];
  const lo = Math.min(...values), hi = Math.max(...values), w = (hi - lo) / bins || 1, out = Array.from({ length: bins }, (_, i) => ({ x: Math.round(lo + i * w), n: 0 }));
  for (const v of values) out[Math.min(bins - 1, Math.floor((v - lo) / w))].n++;
  return out;
}
export const PII_RULES = [["email", /[\w.+-]+@[\w-]+\.[\w.]+/g], ["phone", /\+?\d[\d\s().-]{8,}\d/g], ["ssn", /\b\d{3}-\d{2}-\d{4}\b/g]];
export const piiScan = (text) => PII_RULES.filter(([, re]) => { re.lastIndex = 0; return re.test(text); }).map(([k]) => k);
export const detectLang = (text) => { const t = tokenize(text); if (!t.length) return "und"; const fr = t.filter((w) => ["le", "la", "les", "des", "est", "une", "pour", "dans", "avec", "sur"].includes(w)).length, en = t.filter((w) => ["the", "of", "and", "is", "to", "for", "with"].includes(w)).length; return fr > en && fr >= 2 ? "fr" : "en"; };
const shingles = (text, k = 3) => { const t = tokenize(text), s = new Set(); for (let i = 0; i + k <= t.length; i++) s.add(t.slice(i, i + k).join(" ")); return s; };
export const jaccard = (a, b) => { let i = 0; for (const x of a) if (b.has(x)) i++; return i / Math.max(1, a.size + b.size - i); };
/** Near-duplicate clusters among chunks (Jaccard of 3-word shingles >= threshold). Union-find; clusters of size >= 2. */
export function duplicateClusters(chunks, threshold = 0.6) {
  const sh = chunks.map((c) => shingles(c.text)), p = chunks.map((_, i) => i), f = (i) => (p[i] === i ? i : (p[i] = f(p[i])));
  const sim = new Map();
  for (let i = 0; i < chunks.length; i++) for (let j = i + 1; j < chunks.length; j++) { const s = jaccard(sh[i], sh[j]); if (s >= threshold) { p[f(i)] = f(j); sim.set(i + ":" + j, s); } }
  const g = new Map(); chunks.forEach((c, i) => { const r = f(i); if (!g.has(r)) g.set(r, []); g.get(r).push(i); });
  return [...g.values()].filter((m) => m.length > 1).map((m) => ({ ids: m.map((i) => chunks[i].id), uris: [...new Set(m.map((i) => chunks[i].uri))], exact: m.every((i) => chunks[i].text === chunks[m[0]].text) }));
}
export function corpusStats(chunks) {
  const docs = new Set(chunks.map((c) => c.uri)), by = (f) => { const m = {}; chunks.forEach((c) => { const k = f(c); m[k] = (m[k] || 0) + 1; }); return m; };
  const dc = duplicateClusters(chunks);
  return {
    documents: docs.size, chunks: chunks.length, totalTokens: chunks.reduce((a, c) => a + c.tokens, 0),
    sizeHist: histogram(chunks.map((c) => c.tokens), 10), bySource: by((c) => c.uri.split("/").pop()),
    byMeta: (k) => by((c) => String(c.metadata?.[k] ?? "(none)")), metaKeys: [...new Set(chunks.flatMap((c) => Object.keys(c.metadata || {})))],
    dupClusters: dc, piiChunks: chunks.filter((c) => piiScan(c.text).length), langs: by((c) => detectLang(c.text)),
    avgDocTokens: Math.round(chunks.reduce((a, c) => a + c.tokens, 0) / Math.max(1, docs.size)),
  };
}

// ── provenance (post-RAG) ──
/** For each answer sentence: best supporting chunk by content-token coverage. grounded when coverage >= minCover. */
export function provenance(answer, chunks, minCover = 0.5) {
  return splitSentences(answer).map((s) => {
    const q = contentTokens(s).map(stem); let best = null;
    for (const c of chunks) { const set = new Set(contentTokens(c.text).map(stem)), cov = q.length ? q.filter((t) => set.has(t)).length / q.length : 0; if (!best || cov > best.cover) best = { chunkId: c.id, uri: c.uri, cover: cov, span: bestSpan(s, c.text) }; }
    return { text: s, grounded: !!best && best.cover >= minCover, ...(best || { chunkId: null, uri: null, cover: 0, span: null }) };
  });
}
function bestSpan(sentence, text) { // the source sentence of the chunk that overlaps most with the answer sentence
  const q = new Set(contentTokens(sentence).map(stem)); let b = null;
  for (const s of splitSentences(text)) { const n = contentTokens(s).map(stem).filter((t) => q.has(t)).length; if (!b || n > b.n) b = { n, text: s }; }
  return b?.text || null;
}

// ── deterministic metrics ──
export const DEFAULT_THRESHOLDS = { hitRate: 0.8, mrr: 0.6, contextPrecision: 0.5, contextRecall: 0.6, citationAccuracy: 0.7, faithfulness: 0.8, answerRelevance: 0.4 };
export const METRIC_LABELS = { hitRate: "Hit rate@k", mrr: "MRR@k", contextPrecision: "Context precision", contextRecall: "Context recall", citationAccuracy: "Citation accuracy", faithfulness: "Faithfulness", answerRelevance: "Answer relevance" };
const matchesSource = (uri, expected) => (expected || []).some((e) => String(uri).includes(e));
const isRelevant = (chunk, row) => (row.expectedSources?.length ? matchesSource(chunk.uri, row.expectedSources) : false);
const REFUSAL = /\b(cannot|can't|unable|don't have|do not have|no (relevant )?information|not (found|covered))\b/i;
export const isRefusal = (a) => !a || REFUSAL.test(a);

/** row: {question, expectedSources:[], expectedAnswer}; res: {retrieved:[{id,uri,text}], answer, citations:[uri]}. Returns the 7 metrics in 0..1. */
export function scoreRow(row, res, k = 5) {
  const top = (res.retrieved || []).slice(0, k), expectsAnswer = !!(row.expectedSources?.length || row.expectedAnswer);
  const rel = top.map((c) => isRelevant(c, row));
  const firstRel = rel.indexOf(true);
  const hitRate = expectsAnswer ? (firstRel >= 0 ? 1 : 0) : (top.length === 0 ? 1 : 0);
  const mrr = expectsAnswer ? (firstRel >= 0 ? 1 / (firstRel + 1) : 0) : hitRate;
  let seen = 0, ap = 0; rel.forEach((r, i) => { if (r) { seen++; ap += seen / (i + 1); } });
  const contextPrecision = expectsAnswer ? (seen ? ap / seen : 0) : hitRate;
  const exp = [...new Set(contentTokens(row.expectedAnswer).map(stem))], ctx = new Set(top.flatMap((c) => contentTokens(c.text).map(stem)));
  const contextRecall = exp.length ? exp.filter((t) => ctx.has(t)).length / exp.length : (expectsAnswer ? hitRate : hitRate);
  const cites = res.citations || [];
  const citationAccuracy = expectsAnswer ? (cites.length ? cites.filter((u) => matchesSource(u, row.expectedSources)).length / cites.length : 0) : (cites.length === 0 ? 1 : 0);
  const prov = provenance(res.answer || "", top.length ? top : [], 0.5);
  const faithfulness = isRefusal(res.answer) ? (expectsAnswer ? 1 : 1) : (prov.length ? prov.filter((p) => p.grounded).length / prov.length : 0);
  const a = contentTokens(res.answer).map(stem), e = exp.length ? exp : contentTokens(row.question).map(stem), aset = new Set(a), eset = new Set(e);
  const common = [...aset].filter((t) => eset.has(t)).length, pr = aset.size ? common / aset.size : 0, rc = eset.size ? common / eset.size : 0;
  const answerRelevance = expectsAnswer ? (pr + rc ? (2 * pr * rc) / (pr + rc) : 0) : (isRefusal(res.answer) ? 1 : 0);
  return { hitRate, mrr, contextPrecision, contextRecall, citationAccuracy, faithfulness, answerRelevance };
}
export function aggregate(scores) {
  const keys = Object.keys(METRIC_LABELS), out = {};
  for (const k of keys) out[k] = scores.length ? scores.reduce((a, s) => a + s[k], 0) / scores.length : 0;
  return out;
}
export const verdicts = (agg, thr = DEFAULT_THRESHOLDS) => Object.fromEntries(Object.keys(METRIC_LABELS).map((k) => [k, agg[k] >= (thr[k] ?? 0)]));
/** Compare run A and B: per metric delta and winner (tie within 0.005). */
export const compareRuns = (a, b) => Object.keys(METRIC_LABELS).map((k) => { const d = b.aggregate[k] - a.aggregate[k]; return { metric: k, a: a.aggregate[k], b: b.aggregate[k], delta: d, winner: Math.abs(d) < 0.005 ? "tie" : d > 0 ? "B" : "A" }; });

/** Facilities golden set (matches the fake corpus; for the real facilities-kb edit the sources). */
export const DEFAULT_GOLDEN = [
  { question: "How often must HVAC filters be replaced?", expectedSources: ["hvac-maintenance-policy"], expectedAnswer: "HVAC filters must be replaced every 90 days" },
  { question: "What is the approval limit for work orders requiring a manager?", expectedSources: ["work-order-approval-policy"], expectedAnswer: "Work orders above 5000 dollars need manager approval" },
  { question: "How often are fire extinguishers inspected?", expectedSources: ["fire-safety-handbook"], expectedAnswer: "Fire extinguishers are inspected monthly" },
  { question: "Which elevator had a door fault in March?", expectedSources: ["elevator-service-log"], expectedAnswer: "Elevator 3 door sensor fault in March" },
  { question: "How many visitor parking spaces are reserved?", expectedSources: ["parking-policy"], expectedAnswer: "twenty visitor parking spaces are reserved" },
  { question: "What is the chiller maintenance contract response time?", expectedSources: ["vendor-contract-chillers"], expectedAnswer: "four hour response for critical chiller failures" },
  { question: "What is the CEO's favourite colour?", expectedSources: [], expectedAnswer: "" },
];
