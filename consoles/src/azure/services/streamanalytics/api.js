/* Azure Stream Analytics over the native ARM wire (Microsoft.StreamAnalytics, core/azure_streamanalytics_core.py). */
import { restJson, WIRE_BASE } from "../../../common/wire.js";
import { getSubscription } from "../../kit/arm.js";

export const API_VERSION = "2021-10-01-preview";
const Q = { "api-version": API_VERSION };
const sub = () => `/subscriptions/${getSubscription()}`;
export const jobPath = (rg, name) => `${sub()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.StreamAnalytics/streamingjobs/${encodeURIComponent(name)}`;

export const listJobs = async () => (await restJson("GET", `${sub()}/providers/Microsoft.StreamAnalytics/streamingjobs`, { query: Q })).value || [];
export const getJob = (rg, name) => restJson("GET", jobPath(rg, name), { query: Q });
export const createJob = (rg, name, body) => restJson("PUT", jobPath(rg, name), { query: Q, body });
export const deleteJob = (rg, name) => restJson("DELETE", jobPath(rg, name), { query: Q });
export const startJob = (rg, name, body = {}) => restJson("POST", `${jobPath(rg, name)}/start`, { query: Q, body });
export const stopJob = (rg, name) => restJson("POST", `${jobPath(rg, name)}/stop`, { query: Q, body: {} });
export const putChild = (rg, name, kind, child, body) => restJson("PUT", `${jobPath(rg, name)}/${kind}/${encodeURIComponent(child)}`, { query: Q, body });
export const deleteChild = (rg, name, kind, child) => restJson("DELETE", `${jobPath(rg, name)}/${kind}/${encodeURIComponent(child)}`, { query: Q });
export const testChild = (rg, name, kind, child) => restJson("POST", `${jobPath(rg, name)}/${kind}/${encodeURIComponent(child)}/test`, { query: Q, body: {} });
export const putQuery = (rg, name, query, su = 3) => restJson("PUT", `${jobPath(rg, name)}/transformations/Transformation`, { query: Q, body: { properties: { streamingUnits: su, query } } });
export const testQuery = (rg, name, query) => restJson("POST", `${jobPath(rg, name)}/testquery`, { query: Q, body: { query } });

const H = (a) => ({ "x-ms-version": "2021-12-02", "x-ms-date": new Date().toUTCString(), authorization: `SharedKey ${a}:vyomi-console` });
/** Rows of the job's last output blob (line-separated JSON). */
export async function readOutput(url) {
  const m = /^https:\/\/([^.]+)\.blob\.core\.windows\.net\/(.+)$/.exec(url || "");
  if (!m) return [];
  const res = await fetch(`${WIRE_BASE}/${m[1]}/${m[2].split("/").map(encodeURIComponent).join("/")}`, { headers: H(m[1]) });
  if (!res.ok) throw new Error(`Reading the output blob failed (${res.status}).`);
  return (await res.text()).split("\n").filter(Boolean).map((l) => JSON.parse(l));
}
