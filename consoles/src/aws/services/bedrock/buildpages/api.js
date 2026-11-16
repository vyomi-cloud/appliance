/* Bedrock Build / Assess / Configure over the native wire (core/bedrock_build_core.py + core/bedrock_guardrails_core.py). */
import { awsRest, authHeader, WIRE_BASE, WireError } from "../../../../common/wire.js";
import { ACCOUNT, roleArn } from "../api.js";

const B = (m, p, o) => awsRest("bedrock", m, p, o);
const enc = encodeURIComponent;
export { ACCOUNT, roleArn };
export const tail = (arn) => String(arn || "").split(/[/:]/).filter(Boolean).pop();

/** vnd.amazon.eventstream -> [{type, data}] (frames: total, headersLen, prelude crc, headers, payload, crc). */
export function decodeEvents(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength), td = new TextDecoder(), out = [];
  let off = 0;
  while (off + 16 <= buf.length) {
    const total = dv.getUint32(off), hl = dv.getUint32(off + 4);
    let h = off + 12, type = "";
    while (h < off + 12 + hl) {
      const nl = buf[h]; const name = td.decode(buf.slice(h + 1, h + 1 + nl)); h += 1 + nl;
      const vt = buf[h]; h += 1;
      if (vt === 7) { const vl = dv.getUint16(h); const v = td.decode(buf.slice(h + 2, h + 2 + vl)); h += 2 + vl; if (name === ":event-type") type = v; } else break;
    }
    let data = {};
    try { data = JSON.parse(td.decode(buf.slice(off + 12 + hl, off + total - 4))); } catch { /* binary */ }
    out.push({ type, data }); off += total;
  }
  return out;
}
async function stream(path, body) {
  const res = await fetch(`${WIRE_BASE}${path}`, { method: "POST", headers: { ...authHeader("bedrock"), "content-type": "application/json" }, body: JSON.stringify(body) });
  const buf = new Uint8Array(await res.arrayBuffer());
  if (!res.ok) { let d = {}; try { d = JSON.parse(new TextDecoder().decode(buf)); } catch { /* not json */ } throw new WireError(res.status, d.__type || res.headers.get("x-amzn-errortype"), d.message, ""); }
  return decodeEvents(buf);
}

// ── guardrails
export const listGuardrails = () => B("GET", "/guardrails", { query: { maxResults: "1000" } }).then((r) => r.guardrails || []);
export const listGuardrailVersions = (id) => B("GET", "/guardrails", { query: { guardrailIdentifier: id } }).then((r) => r.guardrails || []);
export const getGuardrail = (id, version = "DRAFT") => B("GET", `/guardrails/${id}`, { query: { guardrailVersion: version } });
export const createGuardrail = (cfg) => B("POST", "/guardrails", { body: cfg });
export const updateGuardrail = (id, cfg) => B("PUT", `/guardrails/${id}`, { body: cfg });
export const createGuardrailVersion = (id, description) => B("POST", `/guardrails/${id}`, { body: description ? { description } : {} });
export const deleteGuardrail = (id) => B("DELETE", `/guardrails/${id}`);
export const applyGuardrail = (id, version, source, content) => B("POST", `/guardrail/${id}/version/${version}/apply`, { body: { source, content } });

// ── prompt management
export const listPrompts = () => B("GET", "/prompts/", { query: { maxResults: "100" } }).then((r) => r.promptSummaries || []);
export const listPromptVersions = (id) => B("GET", "/prompts/", { query: { promptIdentifier: id } }).then((r) => r.promptSummaries || []);
export const getPrompt = (id, version) => B("GET", `/prompts/${id}/`, { query: version && version !== "DRAFT" ? { promptVersion: version } : {} });
export const createPrompt = (b) => B("POST", "/prompts/", { body: b });
export const updatePrompt = (id, b) => B("PUT", `/prompts/${id}/`, { body: b });
export const createPromptVersion = (id) => B("POST", `/prompts/${id}/versions`, { body: {} });
export const deletePrompt = (id, version) => B("DELETE", `/prompts/${id}/`, { query: version ? { promptVersion: version } : {} });

// ── flows
export const listFlows = () => B("GET", "/flows/", { query: { maxResults: "100" } }).then((r) => r.flowSummaries || []);
export const getFlow = (id) => B("GET", `/flows/${id}/`);
export const createFlow = (b) => B("POST", "/flows/", { body: { executionRoleArn: roleArn(), ...b } });
export const updateFlow = (id, b) => B("PUT", `/flows/${id}/`, { body: b });
export const prepareFlow = (id) => B("POST", `/flows/${id}/`, { body: {} });
export const deleteFlow = (id) => B("DELETE", `/flows/${id}/`);
export const listFlowVersions = (id) => B("GET", `/flows/${id}/versions`).then((r) => r.flowVersionSummaries || []);
export const createFlowVersion = (id) => B("POST", `/flows/${id}/versions`, { body: {} });
export const listFlowAliases = (id) => B("GET", `/flows/${id}/aliases`).then((r) => r.flowAliasSummaries || []);
export const createFlowAlias = (id, name, version) => B("POST", `/flows/${id}/aliases`, { body: { name, routingConfiguration: [{ flowVersion: version }] } });
export const deleteFlowAlias = (id, alias) => B("DELETE", `/flows/${id}/aliases/${alias}`);
/** InvokeFlow on the console's test alias (runs the prepared DRAFT). With enableTrace the response also carries the per-node trace events. */
export const invokeFlow = async (id, text, alias = "TSTALIASID", enableTrace = false) => {
  let doc = text;
  try { const j = JSON.parse(text); if (Array.isArray(j)) doc = j; } catch { /* plain text */ }
  const ev = await stream(`/flows/${id}/aliases/${alias}`, { enableTrace, inputs: [{ nodeName: "FlowInputNode", nodeOutputName: "document", content: { document: doc } }] });
  return { outputs: ev.filter((e) => e.type === "flowOutputEvent").map((e) => e.data), reason: ev.find((e) => e.type === "flowCompletionEvent")?.data.completionReason, trace: ev.filter((e) => e.type === "flowTraceEvent").map((e) => e.data.trace) };
};

// ── evaluations
export const listEvaluations = () => B("GET", "/evaluation-jobs", { query: { maxResults: "100" } }).then((r) => r.jobSummaries || []);
export const getEvaluation = (id) => B("GET", `/evaluation-jobs/${enc(id)}`);
export const createEvaluation = (b) => B("POST", "/evaluation-jobs", { body: { roleArn: roleArn(), applicationType: "ModelEvaluation", ...b } });
export const stopEvaluation = (id) => B("POST", `/evaluation-jobs/${enc(id)}/stop`, { body: {} });
export const deleteEvaluation = (id) => B("DELETE", `/evaluation-jobs/${enc(id)}`);

// ── settings (model invocation logging) + model access + optimize
export const getLogging = () => B("GET", "/logging/modelinvocations").then((r) => r.loggingConfig || null);
export const putLogging = (loggingConfig) => B("PUT", "/logging/modelinvocations", { body: { loggingConfig } });
export const deleteLogging = () => B("DELETE", "/logging/modelinvocations");
export const modelAvailability = (id) => B("GET", `/foundation-model-availability/${enc(id)}`);
export const optimizePrompt = async (text, targetModelId) => {
  const ev = await stream("/optimize-prompt", { input: { textPrompt: { text } }, targetModelId });
  return ev.find((e) => e.type === "optimizedPromptEvent")?.data.optimizedPrompt?.textPrompt?.text || "";
};
