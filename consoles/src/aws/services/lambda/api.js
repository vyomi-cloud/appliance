/* Lambda over the native REST+JSON wire (method + versioned path, e.g.
 * /2015-03-31/functions/{name}). Routed by PATH on the Vyomi relay (core/aws_wire_router.py),
 * so restJson() — the shared generic-REST-JSON helper — is the right fit; see
 * core/lambda_core.py for the full path map. */
import { restJson } from "../../../common/wire.js";

const F = "/2015-03-31/functions";
const enc = encodeURIComponent;

export const listFunctions = async () => (await restJson("GET", F)).Functions || [];
export const getFunction = (name) => restJson("GET", `${F}/${enc(name)}`);
export const createFunction = (body) => restJson("POST", F, { body });
export const deleteFunction = (name) => restJson("DELETE", `${F}/${enc(name)}`);
export const updateFunctionCode = (name, code) => restJson("PUT", `${F}/${enc(name)}/code`, { body: code });
export const updateFunctionConfiguration = (name, body) => restJson("PUT", `${F}/${enc(name)}/configuration`, { body });
export const invoke = (name, payload) => restJson("POST", `${F}/${enc(name)}/invocations`, { body: payload ?? {} });
export const recentInvocations = (name) => restJson("GET", `${F}/${enc(name)}/invocations`);

// ── Tags ────────────────────────────────────────────────────────────────────────────────
export const listTags = async (name) => (await restJson("GET", `${F}/${enc(name)}/tags`)).Tags || {};
export const tagResource = (name, tags) => restJson("POST", `${F}/${enc(name)}/tags`, { body: { Tags: tags } });
export const untagResource = (name, keys) => restJson("DELETE", `${F}/${enc(name)}/tags`, { query: { tagKeys: keys.join(",") } });

// ── Function URL ────────────────────────────────────────────────────────────────────────
export async function getFunctionUrlConfig(name) {
  try { return await restJson("GET", `${F}/${enc(name)}/url`); }
  catch (e) { if (e.status === 404) return null; throw e; }
}
export const createFunctionUrlConfig = (name, body) => restJson("POST", `${F}/${enc(name)}/url`, { body });
export const updateFunctionUrlConfig = (name, body) => restJson("PUT", `${F}/${enc(name)}/url`, { body });
export const deleteFunctionUrlConfig = (name) => restJson("DELETE", `${F}/${enc(name)}/url`);

// ── Aliases ─────────────────────────────────────────────────────────────────────────────
export const listAliases = async (name) => (await restJson("GET", `${F}/${enc(name)}/aliases`)).Aliases || [];
export const createAlias = (name, body) => restJson("POST", `${F}/${enc(name)}/aliases`, { body });
export const updateAlias = (name, aliasName, body) => restJson("PUT", `${F}/${enc(name)}/aliases/${enc(aliasName)}`, { body });
export const deleteAlias = (name, aliasName) => restJson("DELETE", `${F}/${enc(name)}/aliases/${enc(aliasName)}`);

// ── Versions ────────────────────────────────────────────────────────────────────────────
export const publishVersion = (name, body) => restJson("POST", `${F}/${enc(name)}/versions`, { body: body || {} });
export const listVersions = async (name) => (await restJson("GET", `${F}/${enc(name)}/versions`)).Versions || [];
export const deleteVersion = (name, version) => restJson("DELETE", `${F}/${enc(name)}`, { query: { Qualifier: version } });

// ── Layers ──────────────────────────────────────────────────────────────────────────────
export const listLayers = async () => (await restJson("GET", "/2015-03-31/layers")).Layers || [];
export const listLayerVersions = async (layerName) => (await restJson("GET", `/2015-03-31/layers/${enc(layerName)}/versions`)).LayerVersions || [];
export const publishLayerVersion = (layerName, body) => restJson("POST", `/2015-03-31/layers/${enc(layerName)}/versions`, { body });
export const deleteLayerVersion = (layerName, version) => restJson("DELETE", `/2015-03-31/layers/${enc(layerName)}/versions/${version}`);

// ── Event source mappings ("Triggers") ─────────────────────────────────────────────────
export const listEventSourceMappings = async (functionName) =>
  (await restJson("GET", "/2015-03-31/event-source-mappings", { query: functionName ? { FunctionName: functionName } : undefined })).EventSourceMappings || [];
export const createEventSourceMapping = (body) => restJson("POST", "/2015-03-31/event-source-mappings", { body });
export const updateEventSourceMapping = (uuid, body) => restJson("PUT", `/2015-03-31/event-source-mappings/${enc(uuid)}`, { body });
export const deleteEventSourceMapping = (uuid) => restJson("DELETE", `/2015-03-31/event-source-mappings/${enc(uuid)}`);

// ── Concurrency / recursion ─────────────────────────────────────────────────────────────
export const putFunctionConcurrency = (name, n) => restJson("PUT", `${F}/${enc(name)}/concurrency`, { body: { ReservedConcurrentExecutions: n } });
export const deleteFunctionConcurrency = (name) => restJson("DELETE", `${F}/${enc(name)}/concurrency`);
export const putFunctionRecursionConfig = (name, value) => restJson("PUT", `${F}/${enc(name)}/recursion-config`, { body: { RecursiveLoop: value } });

// ── Destinations (async invoke config) ─────────────────────────────────────────────────
export async function getFunctionEventInvokeConfig(name) {
  try { return await restJson("GET", `${F}/${enc(name)}/event-invoke-config`); }
  catch (e) { if (e.status === 404) return null; throw e; }
}
export const putFunctionEventInvokeConfig = (name, body) => restJson("PUT", `${F}/${enc(name)}/event-invoke-config`, { body });
export const deleteFunctionEventInvokeConfig = (name) => restJson("DELETE", `${F}/${enc(name)}/event-invoke-config`);

// ── Resource policy ─────────────────────────────────────────────────────────────────────
export async function getPolicy(name) {
  try { return JSON.parse((await restJson("GET", `${F}/${enc(name)}/policy`)).Policy); }
  catch (e) { if (e.status === 404) return null; throw e; }
}

export const DEFAULT_SOURCE = {
  "python3.12": "def handler(event, context):\n    return {\"message\": \"Hello from Lambda!\", \"event\": event}\n",
  "python3.11": "def handler(event, context):\n    return {\"message\": \"Hello from Lambda!\", \"event\": event}\n",
  "python3.10": "def handler(event, context):\n    return {\"message\": \"Hello from Lambda!\", \"event\": event}\n",
};
export const defaultSource = (runtime) => DEFAULT_SOURCE[runtime] || DEFAULT_SOURCE["python3.12"];

/** Event Functions vs Web Functions — the console's own split over one function store:
 *  a function with a Function URL is a "Web Function", everything else is an "Event Function". */
export const isWebFunction = (fn) => !!fn.FunctionUrl || !!fn._hasUrl;

export async function listFunctionsSplit() {
  const fns = await listFunctions();
  const withUrl = await Promise.all(fns.map(async (fn) => {
    const url = await getFunctionUrlConfig(fn.FunctionName);
    return { ...fn, _hasUrl: !!url, _url: url };
  }));
  return { eventFunctions: withUrl.filter((f) => !f._hasUrl), webFunctions: withUrl.filter((f) => f._hasUrl) };
}
