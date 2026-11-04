/* Azure Files over ARM: Microsoft.Storage/storageAccounts/{sa}/fileServices/default/shares (control plane) and the
 * Vyomi content extension .../shares/{share}/items/{path} (the real data plane is SMB/NFS, which a browser cannot speak). */
import { arm, armList, rgPath } from "../../kit/az08.js";

const acct = (a) => `${rgPath(a.resourceGroup)}/providers/Microsoft.Storage/storageAccounts/${a.name}`;
const svc = (a) => `${acct(a)}/fileServices/default`;
const V = "2023-01-01";
export const getFileService = (a) => arm("GET", svc(a), undefined, {}, V);
export const putFileService = (a, properties) => arm("PUT", svc(a), { properties }, {}, V);
export const listShares = (a, deleted) => armList(`${svc(a)}/shares`, deleted ? { $expand: "deleted" } : {});
export const getShare = (a, n) => arm("GET", `${svc(a)}/shares/${n}`, undefined, { $expand: "snapshots" }, V);
export const putShare = (a, n, properties) => arm("PUT", `${svc(a)}/shares/${n}`, { properties }, {}, V);
export const deleteShare = (a, n, q = {}) => arm("DELETE", `${svc(a)}/shares/${n}`, undefined, q, V);
export const restoreShare = (a, n) => arm("POST", `${svc(a)}/shares/${n}/restore`, {}, {}, V);
export const snapshotShare = (a, n) => arm("POST", `${svc(a)}/shares/${n}/snapshot`, {}, {}, V);
export const deleteSnapshot = (a, n, t) => arm("DELETE", `${svc(a)}/shares/${n}/snapshot/${encodeURIComponent(t)}`, undefined, {}, V);
export const listSnapshots = async (a, n) => (await arm("GET", `${svc(a)}/shares/${n}/snapshots`, undefined, {}, V)).value || [];
export const lease = (a, n, body) => arm("POST", `${svc(a)}/shares/${n}/lease`, body, {}, V);
const items = (a, n, p) => `${svc(a)}/shares/${n}/items${p ? "/" + p.split("/").map(encodeURIComponent).join("/") : ""}`;
export const listDir = async (a, n, p, snapshot) => (await arm("GET", items(a, n, p), undefined, snapshot ? { snapshot } : {}, V)).value || [];
export const readFile = (a, n, p, snapshot) => arm("GET", items(a, n, p), undefined, snapshot ? { snapshot } : {}, V);
export const mkdir = (a, n, p, leaseId) => arm("PUT", items(a, n, p), { type: "directory", leaseId }, {}, V);
export const upload = (a, n, p, contentBase64, contentType, leaseId) => arm("PUT", items(a, n, p), { type: "file", contentBase64, contentType, leaseId }, {}, V);
export const deletePath = (a, n, p, leaseId) => arm("DELETE", items(a, n, p), { leaseId }, {}, V);
export const getService = (a, kind) => arm("GET", `${acct(a)}/${kind}/default`, undefined, {}, V);
export const putServiceCors = (a, kind, corsRules) => arm("PUT", `${acct(a)}/${kind}/default`, { properties: { cors: { corsRules } } }, {}, V);
