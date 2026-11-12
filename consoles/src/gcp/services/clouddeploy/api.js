/* Cloud Deploy over the NATIVE clouddeploy.googleapis.com v1 REST API (core/gcp_clouddeploy_core.py). */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
export const DEFAULT_REGION = "us-central1";
const base = (region = DEFAULT_REGION) => `/v1/projects/${e(getProject())}/locations/${e(region)}`;
export const tail = (name) => name.split("/").pop();
export const regionOf = (name) => name.split("/")[3];

export const listPipelines = async () => (await restJson("GET", `${base("-")}/deliveryPipelines`)).deliveryPipelines || [];
export const listTargets = async () => (await restJson("GET", `${base("-")}/targets`)).targets || [];
export const getPipeline = (r, id) => restJson("GET", `${base(r)}/deliveryPipelines/${e(id)}`);
export const createPipeline = (r, id, body) => restJson("POST", `${base(r)}/deliveryPipelines`, { query: { deliveryPipelineId: id }, body });
export const deletePipeline = (r, id) => restJson("DELETE", `${base(r)}/deliveryPipelines/${e(id)}`, { query: { force: "true" } });
export const createTarget = (r, id, body) => restJson("POST", `${base(r)}/targets`, { query: { targetId: id }, body });
export const deleteTarget = (r, id) => restJson("DELETE", `${base(r)}/targets/${e(id)}`);
export const listReleases = async (r, p) => (await restJson("GET", `${base(r)}/deliveryPipelines/${e(p)}/releases`)).releases || [];
export const createRelease = (r, p, id, body) => restJson("POST", `${base(r)}/deliveryPipelines/${e(p)}/releases`, { query: { releaseId: id }, body });
export const abandonRelease = (relName) => restJson("POST", `/v1/${relName}:abandon`, { body: {} });
export const listRollouts = async (relName) => (await restJson("GET", `/v1/${relName}/rollouts`)).rollouts || [];
export const createRollout = (relName, id, targetId) => restJson("POST", `/v1/${relName}/rollouts`, { query: { rolloutId: id }, body: { targetId } });
export const rolloutAction = (roName, verb, body = {}) => restJson("POST", `/v1/${roName}:${verb}`, { body });
export const listJobRuns = async (roName) => (await restJson("GET", `/v1/${roName}/jobRuns`)).jobRuns || [];
export const rollback = (r, p, targetId, rollbackId) => restJson("POST", `${base(r)}/deliveryPipelines/${e(p)}:rollbackTarget`, { body: { targetId, rollbackId } });
