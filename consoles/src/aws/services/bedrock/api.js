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

export const updateAgent = (id, a, patch) => B("PUT", `/agents/${id}/`, { body: { agentName: a.agentName, agentResourceRoleArn: a.agentResourceRoleArn, foundationModel: a.foundationModel, instruction: a.instruction,
  description: a.description, idleSessionTTLInSeconds: a.idleSessionTTLInSeconds, guardrailConfiguration: a.guardrailConfiguration, memoryConfiguration: a.memoryConfiguration,
  promptOverrideConfiguration: a.promptOverrideConfiguration, agentCollaboration: a.agentCollaboration, ...patch } }).then((r) => r.agent);
export const getActionGroup = (id, gid) => B("GET", `/agents/${id}/agentversions/DRAFT/actiongroups/${gid}/`).then((r) => r.agentActionGroup);
export const createActionGroup = (id, body) => B("PUT", `/agents/${id}/agentversions/DRAFT/actiongroups/`, { body }).then((r) => r.agentActionGroup);
export const deleteActionGroup = (id, gid) => B("DELETE", `/agents/${id}/agentversions/DRAFT/actiongroups/${gid}/`);
export const listCollaborators = (id) => B("POST", `/agents/${id}/agentversions/DRAFT/agentcollaborators/`, { body: {} }).then((r) => r.agentCollaboratorSummaries || []);
export const associateCollaborator = (id, body) => B("PUT", `/agents/${id}/agentversions/DRAFT/agentcollaborators/`, { body }).then((r) => r.agentCollaborator);
export const disassociateCollaborator = (id, cid) => B("DELETE", `/agents/${id}/agentversions/DRAFT/agentcollaborators/${cid}/`);
export const getAgentMemory = (id, aliasId, memoryId) => B("GET", `/agents/${id}/agentAliases/${aliasId}/memories`, { query: { memoryId, memoryType: "SESSION_SUMMARY" } }).then((r) => r.memoryContents || []);

/** InvokeAgent returns vnd.amazon.eventstream. Returns { text, citations, traces[], returnControl, files[] }.
 *  opts: { enableTrace, memoryId, sessionState }. A returnControl event (RETURN_CONTROL or requireConfirmation) is returned for the caller to answer
 *  by calling again with sessionState.invocationId + returnControlInvocationResults and no inputText. */
export async function invokeAgent(agentId, aliasId, sessionId, inputText, opts = {}) {
  const body = { ...(inputText ? { inputText } : {}), ...(opts.enableTrace ? { enableTrace: true } : {}), ...(opts.memoryId ? { memoryId: opts.memoryId } : {}), ...(opts.sessionState ? { sessionState: opts.sessionState } : {}) };
  const res = await fetch(`${WIRE_BASE}/agents/${agentId}/agentAliases/${aliasId}/sessions/${sessionId}/text`, {
    method: "POST", headers: { ...authHeader("bedrock"), "content-type": "application/json" }, body: JSON.stringify(body) });
  const buf = new Uint8Array(await res.arrayBuffer());
  if (!res.ok) { let d = {}; try { d = JSON.parse(new TextDecoder().decode(buf)); } catch { /* not json */ } throw new WireError(res.status, d.__type || res.headers.get("x-amzn-errortype"), d.message, ""); }
  const dv = new DataView(buf.buffer);
  let off = 0, text = "", citations = [], traces = [], returnControl = null, files = [];
  while (off + 16 <= buf.length) {
    const total = dv.getUint32(off), hl = dv.getUint32(off + 4);
    const hdr = new TextDecoder().decode(buf.slice(off + 12, off + 12 + hl));
    const payload = buf.slice(off + 12 + hl, off + total - 4);
    try {
      const j = JSON.parse(new TextDecoder().decode(payload));
      if (j.bytes) text += decodeURIComponent(escape(atob(j.bytes)));
      if (j.attribution?.citations) citations = citations.concat(j.attribution.citations);
      if (j.trace) traces.push(j);
      if (j.invocationInputs) returnControl = j;
      if (j.files && hdr.includes("files")) files = files.concat(j.files);
    } catch { /* non-json frame */ }
    off += total;
  }
  return { text, citations, traces, returnControl, files };
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

// ── tokenizer, API keys (IAM service-specific credentials, ServiceName bedrock.amazonaws.com) ──
import { awsQuery, asList, pick } from "../../../common/wire.js";
export const countTokens = (modelId, text) => B("POST", `/model/${enc(modelId)}/count-tokens`, { body: { input: { converse: { messages: [{ role: "user", content: [{ text }] }] } } } }).then((r) => r.inputTokens);
const IAMQ = (a, p) => awsQuery("iam", a, p);
const SVC = "bedrock.amazonaws.com";
const credList = (x) => asList(pick(x, "member")).map((c) => ({ id: c.ServiceSpecificCredentialId, user: c.UserName, status: c.Status, created: c.CreateDate, expires: c.ExpirationDate || "", serviceUser: c.ServiceUserName }));
export const listApiKeys = () => IAMQ("ListServiceSpecificCredentials", { ServiceName: SVC }).then((r) => credList(r.ListServiceSpecificCredentialsResponse.ListServiceSpecificCredentialsResult.ServiceSpecificCredentials));
/** The console's "Generate long-term API keys": a BedrockAPIKey-xxxx IAM user + AmazonBedrockLimitedAccess + a service-specific credential. */
export async function createApiKey(days) {
  const user = `BedrockAPIKey-${Math.random().toString(36).slice(2, 6)}`;
  await IAMQ("CreateUser", { UserName: user });
  await IAMQ("AttachUserPolicy", { UserName: user, PolicyArn: "arn:aws:iam::aws:policy/AmazonBedrockLimitedAccess" }).catch(() => {});
  const r = await IAMQ("CreateServiceSpecificCredential", { UserName: user, ServiceName: SVC, ...(days ? { CredentialAgeDays: String(days) } : {}) });
  const c = r.CreateServiceSpecificCredentialResponse.CreateServiceSpecificCredentialResult.ServiceSpecificCredential;
  return { user, id: c.ServiceSpecificCredentialId, serviceUser: c.ServiceUserName, key: c.ServicePassword, expires: c.ExpirationDate || "" };
}
export const setApiKeyStatus = (c, Status) => IAMQ("UpdateServiceSpecificCredential", { UserName: c.user, ServiceSpecificCredentialId: c.id, Status });
export const resetApiKey = (c) => IAMQ("ResetServiceSpecificCredential", { UserName: c.user, ServiceSpecificCredentialId: c.id }).then((r) => r.ResetServiceSpecificCredentialResponse.ResetServiceSpecificCredentialResult.ServiceSpecificCredential.ServicePassword);
export const deleteApiKey = (c) => IAMQ("DeleteServiceSpecificCredential", { UserName: c.user, ServiceSpecificCredentialId: c.id });
