/* GCP IAM catalog client: loads the verbatim per-service catalog slices (GET /api/iam/gcp/catalog/<svc>, served by Mesh and
 * answered in the browser on Nano), and merges them into one role list + one permission list for the pickers.
 * The catalog carries no per-permission launch status, so every permission is reported "Supported" (never invented). */
import { useEffect, useState } from "react";
import { ROLE_TITLES } from "./api.js";

export const CATALOG_SERVICES = ["aiplatform","apigateway","apphub","artifactregistry","backupdr","bigquery","binaryauthorization","cloudbuild","clouddeploy","cloudfunctions","cloudkms","cloudscheduler","cloudsql","cloudtasks","commerceoffercatalog","compute","consumerprocurement","container","dns","eventarc","firebaseauth","firestore","iam","iap","logging","monitoring","orgpolicy","pubsub","redis","resourcemanager","run","secretmanager","securitycenter","servicehealth","servicenetworking","serviceusage","storage","vpcaccess","workflows"];

// Basic roles are not in the per-service slices' titles consistently; give them stable titles/descriptions.
const BASIC = {
  "roles/owner": ["Owner", "Full access to all resources."],
  "roles/editor": ["Editor", "Edit access to all resources."],
  "roles/viewer": ["Viewer", "View access to most resources."],
};
export const roleProduct = (id) => /^roles\//.test(id) ? (BASIC[id] ? "basic" : id.slice(6).split(".")[0]) : "custom";

let cache = null;
/** Fetch + merge every catalog slice once. iamApi = common/iamEnforce.js client. Missing slices (404) are skipped. */
export function loadCatalog(iamApi) {
  if (cache) return cache;
  cache = (async () => {
    const slices = await Promise.all(CATALOG_SERVICES.map((s) => iamApi.catalog(s).catch(() => null)));
    const roles = new Map(); const perms = new Set();
    for (const c of slices) {
      if (!c) continue;
      for (const p of Object.keys(c.permissions || {})) perms.add(p);
      for (const [id, r] of Object.entries(c.roles || {})) if (!roles.has(id)) roles.set(id, { id, title: r.title || id, desc: r.desc || "", permissions: r.permissions || [], product: roleProduct(id) });
    }
    for (const [id, [title, desc]] of Object.entries(BASIC)) {
      const r = roles.get(id) || { id, permissions: [] };
      roles.set(id, { ...r, id, title, desc: r.desc || desc, product: "basic" });
    }
    for (const r of roles.values()) ROLE_TITLES[r.id] = r.title;
    const permissions = [...perms].sort().map((name) => ({ name, service: name.split(".")[0], status: "Supported" }));
    return { roles: [...roles.values()].sort((a, b) => a.title.localeCompare(b.title)), permissions, loaded: slices.filter(Boolean).length };
  })();
  cache.catch(() => { cache = null; });
  return cache;
}
export function resetCatalogCache() { cache = null; }

export function useCatalog(iamApi) {
  const [s, set] = useState({ loading: true, data: null, error: null });
  useEffect(() => { let on = true; loadCatalog(iamApi).then((d) => on && set({ loading: false, data: d, error: null }), (e) => on && set({ loading: false, data: null, error: e })); return () => { on = false; }; }, [iamApi]);
  return s;
}

/** Custom roles (projects/p/roles/x from the roles API) in the same shape as catalog roles. */
export const fromCustomRole = (r) => ({ id: r.name, title: r.title || r.name.split("/").pop(), desc: r.description || "", permissions: r.includedPermissions || [], product: "custom" });

/** Role search across title, id, description and permission names; ranks title/id matches first. */
export function searchRoles(roles, q) {
  const toks = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!toks.length) return roles;
  const scored = [];
  const phrase = toks.join(" ");
  for (const r of roles) {
    const head = `${r.title} ${r.id}`.toLowerCase(), body = r.desc.toLowerCase();
    let score = head.includes(phrase) ? 10 : 0, ok = true;
    for (const t of toks) {
      if (head.includes(t)) score += 3 + (head.startsWith(t) ? 1 : 0);
      else if (body.includes(t)) score += 2;
      else if (r.permissions.some((p) => p.toLowerCase().includes(t))) score += 1;
      else { ok = false; break; }
    }
    if (ok) scored.push([score, r]);
  }
  return scored.sort((a, b) => b[0] - a[0] || a[1].title.localeCompare(b[1].title)).map((x) => x[1]);
}

/** Property filter for the permission table: tokens "service:storage", "status:supported", "permission:x", "role:id" or free text (AND). */
export function parseFilter(text) {
  const out = { service: [], status: [], text: [], role: [] };
  for (const t of String(text || "").trim().split(/\s+/).filter(Boolean)) {
    const m = /^(service|status|permission|role):(.*)$/i.exec(t);
    if (!m) out.text.push(t.toLowerCase());
    else if (!m[2]) continue;
    else if (m[1].toLowerCase() === "permission") out.text.push(m[2].toLowerCase());
    else out[m[1].toLowerCase()].push(m[2].toLowerCase());
  }
  return out;
}
export function filterPermissions(all, text, roleSet) {
  const f = parseFilter(text);
  return all.filter((p) => {
    const n = p.name.toLowerCase();
    return (!roleSet || roleSet.has(p.name)) && f.service.every((s) => p.service.toLowerCase() === s || n.startsWith(s + ".")) &&
      f.status.every((s) => p.status.toLowerCase() === s) && f.text.every((t) => n.includes(t));
  });
}
