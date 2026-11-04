/* Resource Manager over the NATIVE Cloud Resource Manager v3 REST API
 * (cloudresourcemanager.googleapis.com) — the "Manage resources" page. Every call here is
 * a real operation the google-cloud-resource-manager SDK / gcloud projects commands make;
 * see core/gcp_resourcemanager_core.py for the wire shapes. */
import { restJson } from "../../../common/wire.js";

const e = encodeURIComponent;

export async function searchProjects(query) {
  const r = await restJson("GET", "/v3/projects:search", { query: query ? { query } : undefined });
  return r.projects || [];
}
export const createProject = (projectId, displayName) =>
  restJson("POST", "/v3/projects", { body: { projectId, ...(displayName ? { displayName } : {}) } });
export const renameProject = (projectId, displayName) =>
  restJson("PATCH", `/v3/projects/${e(projectId)}`, { body: { displayName } });
export const deleteProject = (projectId) => restJson("DELETE", `/v3/projects/${e(projectId)}`);

export const validProjectId = (id) => {
  if (!id) return "Project ID is required.";
  if (!/^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(id))
    return "6-30 characters: lowercase letters, digits and hyphens; must start with a letter and can't end with a hyphen.";
  return null;
};

// ── resource hierarchy (organizations / folders) ──
const unwrap = (op) => op?.response || op;
export async function getOrg() {
  const r = await restJson("GET", "/v3/organizations:search");
  return (r.organizations || [])[0] || null;
}
export async function allFolders() {
  const r = await restJson("GET", "/v3/folders:search", { query: { query: "" } });
  return r.folders || [];
}
export const createFolder = async (parent, displayName) => unwrap(await restJson("POST", "/v3/folders", { body: { parent, displayName } }));
export const renameFolder = async (name, displayName) => unwrap(await restJson("PATCH", `/v3/${name}`, { query: { updateMask: "displayName" }, body: { displayName } }));
export const moveFolder = async (name, destinationParent) => unwrap(await restJson("POST", `/v3/${name}:move`, { body: { destinationParent } }));
export const deleteFolder = (name) => restJson("DELETE", `/v3/${name}`);
export const moveProject = async (projectId, destinationParent) => unwrap(await restJson("POST", `/v3/projects/${e(projectId)}:move`, { body: { destinationParent } }));
export const createProjectIn = (projectId, displayName, parent) =>
  restJson("POST", "/v3/projects", { body: { projectId, ...(displayName ? { displayName } : {}), ...(parent ? { parent } : {}) } });
export const parentName = (p) => (p && typeof p === "object" ? `${p.type === "organization" ? "organizations" : "folders"}/${p.id}` : p || "");
export const validFolderName = (n) =>
  /^[A-Za-z0-9][A-Za-z0-9 _-]{1,28}[A-Za-z0-9]$/.test(n || "") ? null : "3-30 characters: letters, digits, spaces, hyphens, underscores; start and end with a letter or digit.";
