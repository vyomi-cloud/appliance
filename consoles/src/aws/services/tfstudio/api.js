/* Infrastructure Studio data. The Terraform diagram/export read Vyomi's own Terraform API (core/tf_export, routes/terraform.py) on the
 * backend that holds the stack: the appliance or a Mesh. Address: localStorage "vyomi.tf.base", else this origin (a local dev
 * console on 127.0.0.1/localhost defaults to the local appliance on :9101). */
const LOCAL = typeof location !== "undefined" && /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
/* Nano answers /api/terraform/* itself (service worker + Pyodide), so with no override it reads its own state; the appliance serves the same API. */
const NANO = typeof document !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content === "nano";
export const getBase = () => {
  try { return (localStorage.getItem("vyomi.tf.base") || (NANO ? location.pathname.split("/v4/")[0] : LOCAL ? "http://127.0.0.1:9101" : "")).replace(/\/$/, ""); } catch (_) { return ""; }
};
export const setBase = (v) => { try { localStorage.setItem("vyomi.tf.base", String(v || "").trim()); } catch (_) { /* private mode */ } };

const get = async (path) => {
  const r = await fetch(getBase() + path);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
};
export const getGraph = () => get("/api/terraform/export/graph");
export const getBundle = (mode) => get(`/api/terraform/export/bundle?format=json&mode=${mode}`);
export const zipUrl = (mode) => `${getBase()}/api/terraform/export/bundle?format=zip&mode=${mode}`;
export const classify = async (types) => {
  const r = await fetch(getBase() + "/api/terraform/classify", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ types }) });
  if (!r.ok) throw new Error(`classify: HTTP ${r.status}`);
  return r.json();
};

/** Download the Terraform bundle. The appliance streams a zip; Nano has no such route, so the zip is built here from the JSON bundle (same files). */
export const downloadZip = async (mode) => {
  let href = zipUrl(mode), revoke = null;
  if (NANO) {
    const { zipBlob, bundleEntries } = await import("./zip.js");
    href = revoke = URL.createObjectURL(zipBlob(bundleEntries(await getBundle(mode))));
  }
  const a = document.createElement("a"); a.href = href; a.download = "vyomi-terraform-export.zip"; document.body.appendChild(a); a.click(); a.remove();
  if (revoke) setTimeout(() => URL.revokeObjectURL(revoke), 10000);
};
