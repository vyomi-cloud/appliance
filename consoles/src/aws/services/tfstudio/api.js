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

/* Import: plan / apply / destroy a Terraform bundle ({ files: name -> text, binaries: name -> base64, variables }) against this backend. */
const post = async (path, body) => {
  const r = await fetch(getBase() + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
};
export const planBundle = (bundle) => post("/api/terraform/plan", bundle);
export const applyBundle = (bundle, targets, known) => post("/api/terraform/apply", { ...bundle, targets, known });
export const destroyBundle = (ledger) => post("/api/terraform/destroy", { ledger });
const LEDGER = "vyomi.tf.ledger";
export const getLedger = () => { try { return JSON.parse(localStorage.getItem(LEDGER) || "[]"); } catch (_) { return []; } };
export const setLedger = (l) => { try { localStorage.setItem(LEDGER, JSON.stringify(l)); } catch (_) { /* private mode */ } };

/** Dropped / pasted files -> request bundle. .tf/.tfvars are text; a .zip is unpacked (its .tf/.tfvars as text, everything else, such as Lambda packages, as base64). */
export async function readBundle(fileList, pasted) {
  const files = {}, binaries = {};
  const b64 = (u8) => { let s = ""; for (let i = 0; i < u8.length; i += 8192) s += String.fromCharCode(...u8.subarray(i, i + 8192)); return btoa(s); };
  const add = (name, u8) => { if (/\.(tf|tfvars)$/.test(name)) files[name] = new TextDecoder().decode(u8); else binaries[name] = b64(u8); };
  for (const f of fileList) {
    if (/\.zip$/i.test(f.name)) {
      const { unzip } = await import("./zip.js"), es = (await unzip(await f.arrayBuffer())).filter((e) => !/(^|\/)(__MACOSX|\.DS_Store)/.test(e.name));
      const top = es.length && es.every((e) => e.name.includes("/") && e.name.split("/")[0] === es[0].name.split("/")[0]) ? es[0].name.split("/")[0] + "/" : "";  // a zip of a folder: strip the folder
      for (const e of es) add(e.name.replace(/^\.\//, "").slice(top.length), e.data);
    }
    else add(f.webkitRelativePath || f.name, new Uint8Array(await f.arrayBuffer()));
  }
  if (pasted && pasted.trim()) files["pasted.tf"] = pasted;
  return { files, binaries };
}
