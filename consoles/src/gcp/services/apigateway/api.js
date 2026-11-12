/* API Gateway over the NATIVE API Gateway API v1 (apigateway.googleapis.com): apis, api configs (OpenAPI 2.0) and gateways.
 * The same wire the google-cloud-api-gateway SDKs and `gcloud api-gateway` speak. */
import { restJson, sendRaw, WIRE_BASE } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
export const REGIONS = ["us-central1", "us-east1", "us-east4", "us-west2", "us-west3", "us-west4", "europe-west1", "europe-west2", "europe-west4", "europe-west6", "asia-east1", "asia-northeast1", "asia-northeast2", "asia-southeast1", "australia-southeast1"];
export const DEFAULT_REGION = "us-central1";
export const ID = /^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$/;

const gl = () => `/v1/projects/${e(getProject())}/locations/global`;
const loc = (r) => `/v1/projects/${e(getProject())}/locations/${e(r)}`;
export const last = (n) => String(n || "").split("/").pop();
export const regionOf = (n) => String(n || "").split("/")[3];
export const apiOfConfig = (cfgName) => String(cfgName || "").split("/")[5];

export const listApis = async () => (await restJson("GET", `${gl()}/apis`)).apis || [];
export const getApi = (id) => restJson("GET", `${gl()}/apis/${e(id)}`);
export const createApi = (id, body) => restJson("POST", `${gl()}/apis`, { body, query: { apiId: id } });
export const deleteApi = (id) => restJson("DELETE", `${gl()}/apis/${e(id)}`);

export const listConfigs = async (api) => (await restJson("GET", `${gl()}/apis/${e(api)}/configs`)).apiConfigs || [];
export const getConfig = (api, id) => restJson("GET", `${gl()}/apis/${e(api)}/configs/${e(id)}`, { query: { view: "FULL" } });
export const createConfig = (api, id, body) => restJson("POST", `${gl()}/apis/${e(api)}/configs`, { body, query: { apiConfigId: id } });
export const deleteConfig = (api, id) => restJson("DELETE", `${gl()}/apis/${e(api)}/configs/${e(id)}`);
/** Every config of every API (for the gateway create form). */
export async function listAllConfigs() {
  const out = [];
  for (const a of await listApis()) for (const c of await listConfigs(last(a.name))) out.push(c);
  return out;
}

export const listGateways = async () => (await restJson("GET", `${loc("-")}/gateways`)).gateways || [];
export const getGateway = (r, id) => restJson("GET", `${loc(r)}/gateways/${e(id)}`);
export const createGateway = (r, id, body) => restJson("POST", `${loc(r)}/gateways`, { body, query: { gatewayId: id } });
export const patchGateway = (r, id, body, updateMask) => restJson("PATCH", `${loc(r)}/gateways/${e(id)}`, { body, query: { updateMask } });
export const deleteGateway = (r, id) => restJson("DELETE", `${loc(r)}/gateways/${e(id)}`);

/* API keys: the API Keys v2 API (apikeys.googleapis.com) that an apiKey security definition is checked against. */
const keysBase = () => `/v2/projects/${e(getProject())}/locations/global/keys`;
export const KEY_ID = /^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$/;
export const listKeys = async () => (await restJson("GET", keysBase())).keys || [];
export const createKey = (id, body) => restJson("POST", keysBase(), { body, query: id ? { keyId: id } : {} });
export const deleteKey = (id) => restJson("DELETE", `${keysBase()}/${e(id)}`);
export const getKeyString = async (id) => (await restJson("GET", `${keysBase()}/${e(id)}/keyString`)).keyString || "";

/* Invoking a gateway. Host-style is the real `<gateway>.gateway.dev` name (not resolvable here); the path-style form is served by the
 * simulator's own router, so it is the one that works: <origin><wire>/gcpgw/<gatewayId>. */
export const invokeBase = (gid) => `${location.origin}${WIRE_BASE}/gcpgw/${e(gid)}`;
export const hostBase = (host) => `https://${host}`;
/** Send one request through the gateway (same-origin wire). Returns {status, headers, text, ms}. */
export async function invoke(gid, method, path, { query = {}, headers = {}, body } = {}) {
  const t = performance.now();
  const clean = Object.fromEntries(Object.entries(query).filter(([, v]) => v !== "" && v != null));
  const r = await sendRaw(method, `/gcpgw/${e(gid)}${path.startsWith("/") ? path : "/" + path}`, { query: clean, headers, body: ["GET", "HEAD"].includes(method) ? undefined : body });
  return { status: r.status, headers: Object.fromEntries(r.headers.entries()), text: r.text, ms: Math.round(performance.now() - t) };
}
export const curlFor = (url, method, { headers = {}, query = {}, body } = {}) => {
  const q = new URLSearchParams(Object.entries(query).filter(([, v]) => v)).toString();
  const h = Object.entries(headers).map(([k, v]) => ` -H '${k}: ${v}'`).join("");
  return `curl -i -X ${method}${h}${body ? ` -d '${body}'` : ""} '${url}${q ? "?" + q : ""}'`;
};

export const b64 = (text) => btoa(unescape(encodeURIComponent(text)));
export const SAMPLE_SPEC = `swagger: "2.0"
info:
  title: hello-api
  version: "1.0"
schemes:
  - https
produces:
  - application/json
x-google-backend:
  address: https://hello-abc123-uc.a.run.app
paths:
  /hello:
    get:
      operationId: hello
      responses:
        "200":
          description: A successful response
`;
