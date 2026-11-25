/* Client for GET|POST <wire>/api/iam/<cloud>/governance/<what> (core/iam_governance.py): hierarchy trees, effective policies and
 * "what would this guardrail do" checks, read from the same stores and engines the enforcement gate uses. Same on Mesh and Nano. */
import { WIRE_BASE } from "./wire.js";
import { iamBase } from "./iamEnforce.js";

export async function gov(cloud, what, { method = "GET", query, body } = {}) {
  const qs = query ? "?" + new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString() : "";
  const f = (...a) => (window.__vyomiIamFetch || fetch)(...a);
  const res = await f(`${iamBase(WIRE_BASE)}/${cloud}/governance/${what}${qs}`, {
    method, headers: body === undefined ? {} : { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let data = {}; try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!res.ok) throw Object.assign(new Error(data.error?.message || data.error || `Governance API HTTP ${res.status}`), { status: res.status });
  return data;
}
