/* Amazon Bedrock over the native wire: control plane + runtime (signing name `bedrock`), AgentCore (`bedrock-agentcore`).
 * The local model behind every call is the Vyomi local-LLM seam (llama.cpp offline, WebLLM on Nano). */
import { awsRest, authHeader, WIRE_BASE, WireError, s3 as s3call } from "../../../common/wire.js";

const B = (m, p, o) => awsRest("bedrock", m, p, o);
const AC = (m, p, o) => awsRest("bedrock-agentcore", m, p, o);
const enc = encodeURIComponent;
export const ACCOUNT = "123456789012";
export const roleArn = (n = "vyomi-bedrock") => `arn:aws:iam::${ACCOUNT}:role/${n}`;

// ── models + inference ──
export const listModels = () => B("GET", "/foundation-models").then((r) => r.modelSummaries || []);
export const converse = (modelId, text, { system, maxTokens = 256, temperature = 0.5 } = {}) =>
  B("POST", `/model/${enc(modelId)}/converse`, { body: { messages: [{ role: "user", content: [{ text }] }], ...(system ? { system: [{ text: system }] } : {}), inferenceConfig: { maxTokens, temperature } } });

// ── knowledge bases ──
export const listKnowledgeBases = () => B("POST", "/knowledgebases/", { body: {} }).then((r) => r.knowledgeBaseSummaries || []);
export const getKnowledgeBase = (id) => B("GET", `/knowledgebases/${id}`).then((r) => r.knowledgeBase);
export const createKnowledgeBase = (name, embeddingModelArn) => B("PUT", "/knowledgebases/", { body: {
  name, roleArn: roleArn(), knowledgeBaseConfiguration: { type: "VECTOR", vectorKnowledgeBaseConfiguration: { embeddingModelArn } }, storageConfiguration: { type: "OPENSEARCH_SERVERLESS" } } }).then((r) => r.knowledgeBase);
export const deleteKnowledgeBase = (id) => B("DELETE", `/knowledgebases/${id}`);
export const listDataSources = (kb) => B("POST", `/knowledgebases/${kb}/datasources/`, { body: {} }).then((r) => r.dataSourceSummaries || []);
export const createDataSource = (kb, name, bucket, prefix, maxTokens) => B("PUT", `/knowledgebases/${kb}/datasources/`, { body: {
  name, dataSourceConfiguration: { type: "S3", s3Configuration: { bucketArn: `arn:aws:s3:::${bucket}`, ...(prefix ? { inclusionPrefixes: [prefix] } : {}) } },
  vectorIngestionConfiguration: { chunkingConfiguration: { chunkingStrategy: "FIXED_SIZE", fixedSizeChunkingConfiguration: { maxTokens: Number(maxTokens) || 300, overlapPercentage: 20 } } } } }).then((r) => r.dataSource);
export const startIngestion = (kb, ds) => B("PUT", `/knowledgebases/${kb}/datasources/${ds}/ingestionjobs/`, { body: {} }).then((r) => r.ingestionJob);
export const listIngestionJobs = (kb, ds) => B("POST", `/knowledgebases/${kb}/datasources/${ds}/ingestionjobs/`, { body: {} }).then((r) => r.ingestionJobSummaries || []);
export const getIngestionJob = (kb, ds, id) => B("GET", `/knowledgebases/${kb}/datasources/${ds}/ingestionjobs/${id}`).then((r) => r.ingestionJob);
export const retrieve = (kb, text, n = 5) => B("POST", `/knowledgebases/${kb}/retrieve`, { body: { retrievalQuery: { text }, retrievalConfiguration: { vectorSearchConfiguration: { numberOfResults: n } } } }).then((r) => r.retrievalResults || []);
export const retrieveAndGenerate = (kb, text, modelArn) => B("POST", "/retrieveAndGenerate", { body: { input: { text }, retrieveAndGenerateConfiguration: { type: "KNOWLEDGE_BASE", knowledgeBaseConfiguration: { knowledgeBaseId: kb, modelArn } } } });
export const listBuckets = async () => {
  const r = await s3call("GET", "/");
  const b = r.ListAllMyBucketsResult?.Buckets?.Bucket;
  return (b ? [].concat(b) : []).map((x) => x.Name);
};

// ── agents ──
export const listAgents = () => B("GET", "/agents/").then((r) => r.agentSummaries || []);
export const getAgent = (id) => B("GET", `/agents/${id}/`).then((r) => r.agent);
export const createAgent = (input) => B("PUT", "/agents/", { body: { agentResourceRoleArn: roleArn(), ...input } }).then((r) => r.agent);
export const prepareAgent = (id) => B("POST", `/agents/${id}/`);
export const deleteAgent = (id) => B("DELETE", `/agents/${id}/`, { query: { skipResourceInUseCheck: "true" } });
export const listAliases = (id) => B("POST", `/agents/${id}/agentaliases/`, { body: {} }).then((r) => r.agentAliasSummaries || []);
export const createAlias = (id, name) => B("PUT", `/agents/${id}/agentaliases/`, { body: { agentAliasName: name } }).then((r) => r.agentAlias);
export const deleteAlias = (id, alias) => B("DELETE", `/agents/${id}/agentaliases/${alias}/`);
export const listAgentKbs = (id) => B("POST", `/agents/${id}/agentversions/DRAFT/knowledgebases/`, { body: {} }).then((r) => r.agentKnowledgeBaseSummaries || []);
export const associateKb = (id, kb, description) => B("PUT", `/agents/${id}/agentversions/DRAFT/knowledgebases/`, { body: { knowledgeBaseId: kb, description } });
export const disassociateKb = (id, kb) => B("DELETE", `/agents/${id}/agentversions/DRAFT/knowledgebases/${kb}`);
export const listActionGroups = (id) => B("POST", `/agents/${id}/agentversions/DRAFT/agentactiongroups/`, { body: {} }).then((r) => r.actionGroupSummaries || []);

/** InvokeAgent returns vnd.amazon.eventstream: decode the `chunk` events' base64 bytes. */
export async function invokeAgent(agentId, aliasId, sessionId, inputText) {
  const res = await fetch(`${WIRE_BASE}/agents/${agentId}/agentAliases/${aliasId}/sessions/${sessionId}/text`, {
    method: "POST", headers: { ...authHeader("bedrock"), "content-type": "application/json" }, body: JSON.stringify({ inputText }) });
  const buf = new Uint8Array(await res.arrayBuffer());
  if (!res.ok) { let d = {}; try { d = JSON.parse(new TextDecoder().decode(buf)); } catch { /* not json */ } throw new WireError(res.status, d.__type || res.headers.get("x-amzn-errortype"), d.message, ""); }
  const dv = new DataView(buf.buffer);
  let off = 0, text = "", citations = [];
  while (off + 16 <= buf.length) {
    const total = dv.getUint32(off), hl = dv.getUint32(off + 4);
    const payload = buf.slice(off + 12 + hl, off + total - 4);
    try {
      const j = JSON.parse(new TextDecoder().decode(payload));
      if (j.bytes) text += decodeURIComponent(escape(atob(j.bytes)));
      if (j.attribution?.citations) citations = citations.concat(j.attribution.citations);
    } catch { /* non-json frame */ }
    off += total;
  }
  return { text, citations };
}

// ── AgentCore ──
export const listRuntimes = () => AC("GET", "/runtimes/").then((r) => r.agentRuntimes || []);
export const getRuntime = (id) => AC("GET", `/runtimes/${enc(id)}/`);
export const createRuntime = (name, containerUri, networkMode = "PUBLIC") => AC("POST", "/runtimes/", { body: { agentRuntimeName: name, agentRuntimeArtifact: { containerConfiguration: { containerUri } }, roleArn: roleArn("vyomi-agentcore"), networkConfiguration: { networkMode } } });
export const deleteRuntime = (id) => AC("DELETE", `/runtimes/${enc(id)}/`);
export const listGateways = () => AC("GET", "/gateways/").then((r) => r.items || []);
export const getGateway = (id) => AC("GET", `/gateways/${id}/`);
export const createGateway = (name, authorizerType = "NONE", description = "") => AC("POST", "/gateways/", { body: { name, protocolType: "MCP", authorizerType, roleArn: roleArn("vyomi-agentcore"), description } });
export const deleteGateway = (id) => AC("DELETE", `/gateways/${id}/`);
export const listTargets = (gw) => AC("GET", `/gateways/${gw}/targets/`).then((r) => r.items || []);
export const getTarget = (gw, id) => AC("GET", `/gateways/${gw}/targets/${id}/`);
export const createLambdaTarget = (gw, name, lambdaArn, tools) => AC("POST", `/gateways/${gw}/targets/`, { body: { name, targetConfiguration: { mcp: { lambda: { lambdaArn, toolSchema: { inlinePayload: tools } } } } } });
export const deleteTarget = (gw, id) => AC("DELETE", `/gateways/${gw}/targets/${id}/`);
export const mcp = (gw, method, params) => AC("POST", `/gateways/${gw}/mcp`, { body: { jsonrpc: "2.0", id: Date.now(), method, ...(params ? { params } : {}) } });
export async function listLambdas() {
  const r = await awsRest("lambda", "GET", "/2015-03-31/functions");
  return (r.Functions || []).map((f) => ({ name: f.FunctionName, arn: f.FunctionArn }));
}
