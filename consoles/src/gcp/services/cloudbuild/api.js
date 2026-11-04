/* Cloud Build over the NATIVE cloudbuild.googleapis.com v1 REST API (core/gcp_cloudbuild_core.py). */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const base = () => `/v1/projects/${e(getProject())}`;
export const listBuilds = async () => (await restJson("GET", `${base()}/builds`)).builds || [];
export const getBuild = (id) => restJson("GET", `${base()}/builds/${e(id)}`);
export const retryBuild = (id) => restJson("POST", `${base()}/builds/${e(id)}:retry`, { body: {} });
export const createBuild = (body) => restJson("POST", `${base()}/builds`, { body });
export const listTriggers = async () => (await restJson("GET", `${base()}/triggers`)).triggers || [];
export const createTrigger = (body) => restJson("POST", `${base()}/triggers`, { body });
export const patchTrigger = (id, body) => restJson("PATCH", `${base()}/triggers/${e(id)}`, { body });
export const deleteTrigger = (id) => restJson("DELETE", `${base()}/triggers/${e(id)}`);
export const runTrigger = (id, branchName) => restJson("POST", `${base()}/triggers/${e(id)}:run`, { body: { branchName } });
export const pushToRepo = (body) => restJson("POST", `${base()}/triggers:vyomiPush`, { body });
export const duration = (b) => (b.startTime && b.finishTime ? `${Math.max(0, (new Date(b.finishTime) - new Date(b.startTime)) / 1000).toFixed(1)}s` : "—");
