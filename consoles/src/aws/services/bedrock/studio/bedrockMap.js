/* AWS-only: RAG design <-> Bedrock API shapes (chunkingConfiguration / retrievalConfiguration / rerank ARN). */
import { defaultDesign } from "../../../../common/ragstudio/engine.js";

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
