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
