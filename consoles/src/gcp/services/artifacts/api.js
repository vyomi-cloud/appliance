/* Artifact Registry over the NATIVE Artifact Registry REST API v1 (the same wire
 * google-cloud-artifact-registry, gcloud artifacts and the Docker/Maven/npm/Python
 * registry clients see). Every call here is a real AR API operation — except
 * `pushSample`, a Vyomi-only console convenience (see core/gcp_artifactregistry_core.py):
 * there is no real AR method that creates package data, only `docker push` et al. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const base = () => `/v1/projects/${e(getProject())}`;
const repoPath = (location, id) => `${base()}/locations/${e(location)}/repositories/${e(id)}`;

export async function listRepositories() {
  const r = await restJson("GET", `${base()}/locations/-/repositories`);
  return (r.repositories || []).map(withIds);
}
function withIds(repo) {
  const parts = repo.name.split("/");
  return { ...repo, id: parts[5], location: parts[3] };
}
export const getRepository = (location, id) => restJson("GET", repoPath(location, id)).then(withIds);
export const createRepository = (id, location, body) =>
  restJson("POST", `${base()}/locations/${e(location)}/repositories`, { query: { repositoryId: id }, body });
export const patchRepository = (location, id, body, updateMask) =>
  restJson("PATCH", repoPath(location, id), { query: updateMask ? { updateMask } : undefined, body });
export const deleteRepository = (location, id) => restJson("DELETE", repoPath(location, id));
export const pushSample = (location, id, body) => restJson("POST", `${repoPath(location, id)}:pushSample`, { body });

export const getIamPolicy = (location, id) => restJson("POST", `${repoPath(location, id)}:getIamPolicy`);
export const setIamPolicy = (location, id, policy) => restJson("POST", `${repoPath(location, id)}:setIamPolicy`, { body: { policy } });

export async function listPackages(location, id) {
  const r = await restJson("GET", `${repoPath(location, id)}/packages`);
  return r.packages || [];
}
export const getPackage = (location, id, pkg) => restJson("GET", `${repoPath(location, id)}/packages/${pkg}`);
export const deletePackage = (location, id, pkg) => restJson("DELETE", `${repoPath(location, id)}/packages/${pkg}`);

export async function listVersions(location, id, pkg) {
  const r = await restJson("GET", `${repoPath(location, id)}/packages/${pkg}/versions`);
  return r.versions || [];
}
export const batchDeleteVersions = (location, id, pkg, names) =>
  restJson("POST", `${repoPath(location, id)}/packages/${pkg}/versions:batchDelete`, { body: { names } });

export async function listTags(location, id, pkg) {
  const r = await restJson("GET", `${repoPath(location, id)}/packages/${pkg}/tags`);
  return r.tags || [];
}
export const createTag = (location, id, pkg, tagId, version) =>
  restJson("POST", `${repoPath(location, id)}/packages/${pkg}/tags`, { query: { tagId }, body: { version } });
export const deleteTag = (location, id, pkg, tagId) => restJson("DELETE", `${repoPath(location, id)}/packages/${pkg}/tags/${e(tagId)}`);

export const getProjectSettings = () => restJson("GET", `${base()}/projectSettings`);
export const updateProjectSettings = (legacyRedirectionState) =>
  restJson("PATCH", `${base()}/projectSettings`, { body: { legacyRedirectionState } });

// ── console helpers (labels, formats, derived fields) ───────────────────────────────────
export const FORMAT_LABEL = {
  DOCKER: "Docker", MAVEN: "Maven", NPM: "npm", PYTHON: "Python", APT: "Apt", YUM: "Yum",
  GO: "Go", KFP: "Kubeflow Pipelines", GENERIC: "Generic", GOOGET: "GooGet",
};
export const MODE_LABEL = { STANDARD_REPOSITORY: "Standard", REMOTE_REPOSITORY: "Remote", VIRTUAL_REPOSITORY: "Virtual" };
export const MULTI_REGIONS = ["us", "europe", "asia"];
export const REGIONS = [
  "us-central1", "us-east1", "us-east4", "us-west1", "us-west2", "europe-west1", "europe-west2",
  "europe-west4", "asia-east1", "asia-northeast1", "asia-southeast1",
];
export const locationTypeLabel = (location) => (MULTI_REGIONS.includes(location) ? "Multi-region" : "Region");
export const encryptionLabel = (repo) => (repo.kmsKeyName ? "Customer-managed" : "Google-managed");
export const sizeHuman = (bytes) => {
  let n = Number(bytes || 0);
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${i ? n.toFixed(1) : n} ${u[i]}`;
};
export const pkgIdOf = (pkg) => pkg.name.split("/packages/").pop();
export const versionIdOf = (ver) => ver.name.split("/versions/").pop();
export const tagIdOf = (tag) => tag.name.split("/tags/").pop();

export const validRepoId = (id) => {
  if (!id) return "A repository ID is required.";
  if (!/^[a-z][a-z0-9-]{0,62}$/.test(id) || id.endsWith("-")) return "Use 1-63 lowercase letters, numbers or hyphens, starting with a letter.";
  return null;
};
