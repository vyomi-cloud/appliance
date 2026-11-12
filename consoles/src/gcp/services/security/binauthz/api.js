/* Binary Authorization over the NATIVE binaryauthorization.googleapis.com v1 REST API (core/gcp_binauthz_core.py). */
import { restJson } from "../../../../common/wire.js";
import { getProject } from "../../../project.js";

const p = () => `/v1/projects/${encodeURIComponent(getProject())}`;
export const getPolicy = () => restJson("GET", `${p()}/policy`);
export const putPolicy = (body) => restJson("PUT", `${p()}/policy`, { body });
export const listAttestors = async () => (await restJson("GET", `${p()}/attestors`)).attestors || [];
export const createAttestor = (id, body) => restJson("POST", `${p()}/attestors`, { query: { attestorId: id }, body });
export const deleteAttestor = (name) => restJson("DELETE", `/v1/${name}`);
export const listOccurrences = async () => (await restJson("GET", `${p()}/occurrences`)).occurrences || [];
export const createOccurrence = (body) => restJson("POST", `${p()}/occurrences`, { body });
export const listPlatformPolicies = async () => (await restJson("GET", `${p()}/platforms/cloudRun/policies`)).policies || [];
export const decisions = async () => (await restJson("GET", `${p()}/policy:decisions`)).decisions || [];
export const evaluate = (image) => restJson("POST", `${p()}/policy:evaluate`, { body: { image } });
