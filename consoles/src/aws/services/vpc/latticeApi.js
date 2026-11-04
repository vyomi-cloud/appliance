/* VPC Lattice over its native REST-JSON wire (SigV4 scope `vpc-lattice`) -> core/vpc_lattice_core.py. */
import { awsRest } from "../../../common/wire.js";

const R = (method, path, opts) => awsRest("vpc-lattice", method, path, opts);
const enc = encodeURIComponent;
const items = (r) => r.items || [];

export const listServiceNetworks = () => R("GET", "/servicenetworks").then(items);
export const getServiceNetwork = (id) => R("GET", `/servicenetworks/${id}`);
export const createServiceNetwork = (b) => R("POST", "/servicenetworks", { body: b });
export const updateServiceNetwork = (id, b) => R("PATCH", `/servicenetworks/${id}`, { body: b });
export const deleteServiceNetwork = (id) => R("DELETE", `/servicenetworks/${id}`);

export const listServices = () => R("GET", "/services").then(items);
export const getService = (id) => R("GET", `/services/${id}`);
export const createService = (b) => R("POST", "/services", { body: b });
export const deleteService = (id) => R("DELETE", `/services/${id}`);

export const listListeners = (sid) => R("GET", `/services/${sid}/listeners`).then(items);
export const createListener = (sid, b) => R("POST", `/services/${sid}/listeners`, { body: b });
export const deleteListener = (sid, lid) => R("DELETE", `/services/${sid}/listeners/${lid}`);
export const listRules = (sid, lid) => R("GET", `/services/${sid}/listeners/${lid}/rules`).then(items);
export const getRule = (sid, lid, rid) => R("GET", `/services/${sid}/listeners/${lid}/rules/${rid}`);
export const createRule = (sid, lid, b) => R("POST", `/services/${sid}/listeners/${lid}/rules`, { body: b });
export const deleteRule = (sid, lid, rid) => R("DELETE", `/services/${sid}/listeners/${lid}/rules/${rid}`);

export const listTargetGroups = () => R("GET", "/targetgroups").then(items);
export const getTargetGroup = (id) => R("GET", `/targetgroups/${id}`);
export const createTargetGroup = (b) => R("POST", "/targetgroups", { body: b });
export const deleteTargetGroup = (id) => R("DELETE", `/targetgroups/${id}`);
export const listTargets = (id) => R("POST", `/targetgroups/${id}/listtargets`, { body: {} }).then(items);
export const registerTargets = (id, targets) => R("POST", `/targetgroups/${id}/registertargets`, { body: { targets } });
export const deregisterTargets = (id, targets) => R("POST", `/targetgroups/${id}/deregistertargets`, { body: { targets } });

const assocQ = (coll, q) => R("GET", `/${coll}${q ? `?${q}` : ""}`).then(items);
export const listVpcAssociations = (sn) => assocQ("servicenetworkvpcassociations", sn ? `serviceNetworkIdentifier=${enc(sn)}` : "");
export const createVpcAssociation = (b) => R("POST", "/servicenetworkvpcassociations", { body: b });
export const deleteVpcAssociation = (id) => R("DELETE", `/servicenetworkvpcassociations/${id}`);
export const listServiceAssociations = (sn, svc) => assocQ("servicenetworkserviceassociations", [sn && `serviceNetworkIdentifier=${enc(sn)}`, svc && `serviceIdentifier=${enc(svc)}`].filter(Boolean).join("&"));
export const createServiceAssociation = (b) => R("POST", "/servicenetworkserviceassociations", { body: b });
export const deleteServiceAssociation = (id) => R("DELETE", `/servicenetworkserviceassociations/${id}`);
export const listResourceAssociations = (sn) => assocQ("servicenetworkresourceassociations", sn ? `serviceNetworkIdentifier=${enc(sn)}` : "");
export const createResourceAssociation = (b) => R("POST", "/servicenetworkresourceassociations", { body: b });
export const deleteResourceAssociation = (id) => R("DELETE", `/servicenetworkresourceassociations/${id}`);

export const listResourceGateways = () => R("GET", "/resourcegateways").then(items);
export const getResourceGateway = (id) => R("GET", `/resourcegateways/${id}`);
export const createResourceGateway = (b) => R("POST", "/resourcegateways", { body: b });
export const deleteResourceGateway = (id) => R("DELETE", `/resourcegateways/${id}`);
export const listResourceConfigurations = () => R("GET", "/resourceconfigurations").then(items);
export const getResourceConfiguration = (id) => R("GET", `/resourceconfigurations/${id}`);
export const createResourceConfiguration = (b) => R("POST", "/resourceconfigurations", { body: b });
export const deleteResourceConfiguration = (id) => R("DELETE", `/resourceconfigurations/${id}`);

export const listDomainVerifications = () => R("GET", "/domainverifications").then(items);
export const startDomainVerification = (domainName) => R("POST", "/domainverifications", { body: { domainName } });
export const deleteDomainVerification = (id) => R("DELETE", `/domainverifications/${id}`);

export const getAuthPolicy = (id) => R("GET", `/authpolicy/${id}`);
export const putAuthPolicy = (id, policy) => R("PUT", `/authpolicy/${id}`, { body: { policy } });
export const deleteAuthPolicy = (id) => R("DELETE", `/authpolicy/${id}`);

export const listTags = (arn) => R("GET", `/tags/${enc(arn)}`).then((r) => r.tags || {});
export const tagResource = (arn, tags) => R("POST", `/tags/${enc(arn)}`, { body: { tags } });
export const untagResource = (arn, keys) => R("DELETE", `/tags/${enc(arn)}?${keys.map((k) => `tagKeys=${enc(k)}`).join("&")}`);
