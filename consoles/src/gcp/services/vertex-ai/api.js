/* Vertex AI over the native publisher-model REST API (generateContent / countTokens / embedContent). */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

export const LOCATION = "us-central1";
// mirrors core/ai_models_core.py GEMINI_MODELS / GEMINI_EMBED
export const GEMINI = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"];
export const EMBED = ["text-embedding-005", "text-embedding-004", "gemini-embedding-001"];
const path = (model, op) => `/v1/projects/${encodeURIComponent(getProject())}/locations/${LOCATION}/publishers/google/models/${model}:${op}`;
const contents = (text) => [{ role: "user", parts: [{ text }] }];

export const generate = (model, text, system, maxOutputTokens = 256) => restJson("POST", path(model, "generateContent"), { body: { contents: contents(text), ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}), generationConfig: { maxOutputTokens, temperature: 0.7 } } });
export const countTokens = (model, text) => restJson("POST", path(model, "countTokens"), { body: { contents: contents(text) } });
export const embed = (model, text) => restJson("POST", path(model, "embedContent"), { body: { content: { parts: [{ text }] } } });
/** Multi-turn chat: the whole history is sent as role-tagged `contents` (user / model), exactly like the Vertex AI Studio chat. */
export const chat = (model, history, system, maxOutputTokens = 256) => restJson("POST", path(model, "generateContent"), {
  body: { contents: history.map((m) => ({ role: m.role, parts: [{ text: m.text }] })),
    ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}), generationConfig: { maxOutputTokens, temperature: 0.7 } } });

/* ── Vertex AI control plane (aiplatform.googleapis.com v1 / notebooks v2): /v1/projects/{p}/locations/{l}/{collection} ── */
const e = encodeURIComponent;
export const REGIONS = ["us-central1", "us-east1", "us-east4", "us-west1", "us-west4", "europe-west1", "europe-west2", "europe-west4", "asia-east1", "asia-northeast1", "asia-south1", "asia-southeast1", "australia-southeast1"];
export const ZONES = REGIONS.map((r) => `${r}-a`);
export const pname = (name) => { const s = String(name || "").split("/"); return { project: s[1], location: s[3], coll: s[4], id: s[5], leaf: s[s.length - 1] }; };
export const shortId = (name) => String(name || "").split("/").pop();
export const stateText = (s) => String(s || "").replace(/^(JOB|PIPELINE)_STATE_/, "").replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
export const when = (t) => (t ? new Date(t).toLocaleString() : "—");

const root = (ver, loc) => `/${ver}/projects/${e(getProject())}/locations/${e(loc)}`;
/** Collection path. `parent` is a full parent resource name (projects/../featureGroups/fg) for nested collections. */
export const collPath = (coll, { loc = "-", parent, v2 } = {}) => (parent ? `/v1/${parent}/${coll}` : `${root(v2 ? "v2" : "v1", loc)}/${coll}`);
export const itemPath = (name, v2) => `/${v2 ? "v2" : "v1"}/${name}`;

export async function list(coll, opts = {}) {
  const r = await restJson("GET", collPath(coll, opts), { query: opts.query });
  return Object.values(r).find(Array.isArray) || [];
}
export const get = (name, v2) => restJson("GET", itemPath(name, v2));
export const create = (coll, body, { loc = "us-central1", parent, v2, idKey, id } = {}) =>
  restJson("POST", collPath(coll, { loc, parent, v2 }), { body, query: idKey && id ? { [idKey]: id } : undefined });
export const del = (name, v2) => restJson("DELETE", itemPath(name, v2));
export const verb = (name, v, body = {}, v2) => restJson("POST", `${itemPath(name, v2)}:${v}`, { body });

export const listModelGarden = async (filter) => (await restJson("GET", "/v1/publishers/-/models", { query: filter ? { filter } : undefined })).publisherModels || [];

/** Counts for the dashboard. */
export const COLLECTIONS = [
  ["endpoints", "Endpoints", "endpoints"], ["models", "Models", "models"], ["datasets", "Datasets", "datasets"],
  ["trainingPipelines", "Training pipelines", "training"], ["customJobs", "Custom jobs", "training?tab=custom"],
  ["pipelineJobs", "Pipeline runs", "pipelines"], ["batchPredictionJobs", "Batch predictions", "batch"],
  ["indexes", "Vector indexes", "vector-search"], ["featureGroups", "Feature groups", "feature-store"],
  ["notebookRuntimes", "Colab runtimes", "workbench?tab=runtimes"],
];

/** Deploy a Model Garden / registry model: model upload -> endpoint -> deployModel. Returns the endpoint name. */
export async function deployToNewEndpoint({ displayName, artifactUri, imageUri, loc }) {
  const up = await restJson("POST", `${root("v1", loc)}/models:upload`, { body: { model: { displayName, artifactUri, containerSpec: { imageUri } } } });
  const ep = await create("endpoints", { displayName: `${displayName}-endpoint` }, { loc });
  const epName = ep.response.name;
  await verb(epName, "deployModel", { deployedModel: { model: up.response.name, dedicatedResources: { minReplicaCount: 1, machineSpec: { machineType: "n1-standard-4" } } } });
  return epName;
}

export const uploadModel = (body, loc) => restJson("POST", `${root("v1", loc)}/models:upload`, { body });
