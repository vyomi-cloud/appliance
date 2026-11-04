/* Security Command Center over the NATIVE securitycenter.googleapis.com v2 REST API (core/gcp_scc_core.py). */
import { restJson } from "../../../../common/wire.js";
import { getProject } from "../../../project.js";

const e = encodeURIComponent;
const parent = () => `/v2/projects/${e(getProject())}`;
export const listFindings = async (filter) => {
  const r = await restJson("GET", `${parent()}/sources/-/findings`, { query: { pageSize: 500, ...(filter ? { filter } : {}) } });
  return (r.listFindingsResults || []).map((x) => ({ ...x.finding, _resource: x.resource }));
};
export const groupFindings = async (groupBy, filter) => (await restJson("POST", `${parent()}/sources/-/findings:group`, { body: { groupBy, filter } })).groupByResults || [];
export const setState = (name, state) => restJson("POST", `/v2/${name}:setState`, { body: { state } });
export const setMute = (name, mute) => restJson("POST", `/v2/${name}:setMute`, { body: { mute } });
export const listSources = async () => (await restJson("GET", `${parent()}/sources`)).sources || [];
export const listMuteConfigs = async () => (await restJson("GET", `${parent()}/muteConfigs`)).muteConfigs || [];
export const createMuteConfig = (id, body) => restJson("POST", `${parent()}/muteConfigs`, { query: { muteConfigId: id }, body });
export const deleteMuteConfig = (name) => restJson("DELETE", `/v2/${name}`);
