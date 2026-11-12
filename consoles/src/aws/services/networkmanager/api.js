/* AWS Network Manager over its native REST-JSON wire (SigV4 scope `networkmanager`) -> core/networkmanager_core.py. */
import { awsRest } from "../../../common/wire.js";

const R = (method, path, opts) => awsRest("networkmanager", method, path, opts);
const enc = encodeURIComponent;
const g = (id) => `/global-networks/${enc(id)}`;

export const listGlobalNetworks = () => R("GET", "/global-networks").then((r) => r.GlobalNetworks || []);
export const createGlobalNetwork = (Description, tags) => R("POST", "/global-networks", { body: { Description, Tags: tags } }).then((r) => r.GlobalNetwork);
export const deleteGlobalNetwork = (id) => R("DELETE", g(id));

export const listSites = (id) => R("GET", `${g(id)}/sites`).then((r) => r.Sites || []);
export const createSite = (id, b) => R("POST", `${g(id)}/sites`, { body: b });
export const deleteSite = (id, sid) => R("DELETE", `${g(id)}/sites/${enc(sid)}`);
export const listDevices = (id) => R("GET", `${g(id)}/devices`).then((r) => r.Devices || []);
export const createDevice = (id, b) => R("POST", `${g(id)}/devices`, { body: b });
export const deleteDevice = (id, did) => R("DELETE", `${g(id)}/devices/${enc(did)}`);
export const listLinks = (id) => R("GET", `${g(id)}/links`).then((r) => r.Links || []);
export const createLink = (id, b) => R("POST", `${g(id)}/links`, { body: b });
export const deleteLink = (id, lid) => R("DELETE", `${g(id)}/links/${enc(lid)}`);
export const listAssociations = (id) => R("GET", `${g(id)}/link-associations`).then((r) => r.LinkAssociations || []);
export const associate = (id, DeviceId, LinkId) => R("POST", `${g(id)}/link-associations`, { body: { DeviceId, LinkId } });
export const disassociate = (id, deviceId, linkId) => R("DELETE", `${g(id)}/link-associations`, { query: { deviceId, linkId } });
export const listRegistrations = (id) => R("GET", `${g(id)}/transit-gateway-registrations`).then((r) => r.TransitGatewayRegistrations || []);
export const registerTgw = (id, TransitGatewayArn) => R("POST", `${g(id)}/transit-gateway-registrations`, { body: { TransitGatewayArn } });
export const deregisterTgw = (id, arn) => R("DELETE", `${g(id)}/transit-gateway-registrations/${enc(arn)}`);
