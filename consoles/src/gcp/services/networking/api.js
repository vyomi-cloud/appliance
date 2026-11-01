/* VPC network over the NATIVE Compute Engine REST API v1 (the same wire
 * google-cloud-compute, gcloud compute and Terraform's google provider speak).
 * Every call here is a real compute.googleapis.com operation. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const base = () => `/compute/v1/projects/${e(getProject())}`;

// ── networks ─────────────────────────────────────────────────────────────
export async function listNetworks() {
  const r = await restJson("GET", `${base()}/global/networks`);
  return r.items || [];
}
export const getNetwork = (name) => restJson("GET", `${base()}/global/networks/${e(name)}`);
export const insertNetwork = (body) => restJson("POST", `${base()}/global/networks`, { body });
export const patchNetwork = (name, body) => restJson("PATCH", `${base()}/global/networks/${e(name)}`, { body });
export const deleteNetwork = (name) => restJson("DELETE", `${base()}/global/networks/${e(name)}`);

// ── subnetworks ──────────────────────────────────────────────────────────
export async function listSubnetsInRegion(region) {
  const r = await restJson("GET", `${base()}/regions/${e(region)}/subnetworks`);
  return r.items || [];
}
export async function listAllSubnets() {
  const r = await restJson("GET", `${base()}/aggregated/subnetworks`);
  return Object.values(r.items || {}).flatMap((s) => s.subnetworks || []);
}
export const getSubnet = (region, name) => restJson("GET", `${base()}/regions/${e(region)}/subnetworks/${e(name)}`);
export const insertSubnet = (region, body) => restJson("POST", `${base()}/regions/${e(region)}/subnetworks`, { body });
export const deleteSubnet = (region, name) => restJson("DELETE", `${base()}/regions/${e(region)}/subnetworks/${e(name)}`);

export const subnetsOf = (subnets, networkName) => subnets.filter((s) => s.network.endsWith(`/networks/${networkName}`));
export const nameOf = (selfLinkOrName) => String(selfLinkOrName || "").split("/").pop();

// ── firewalls ────────────────────────────────────────────────────────────
export async function listFirewalls() {
  const r = await restJson("GET", `${base()}/global/firewalls`);
  return r.items || [];
}
export const getFirewall = (name) => restJson("GET", `${base()}/global/firewalls/${e(name)}`);
export const insertFirewall = (body) => restJson("POST", `${base()}/global/firewalls`, { body });
export const patchFirewall = (name, body) => restJson("PATCH", `${base()}/global/firewalls/${e(name)}`, { body });
export const deleteFirewall = (name) => restJson("DELETE", `${base()}/global/firewalls/${e(name)}`);

// ── routes ───────────────────────────────────────────────────────────────
export async function listRoutes() {
  const r = await restJson("GET", `${base()}/global/routes`);
  return r.items || [];
}
export const getRoute = (name) => restJson("GET", `${base()}/global/routes/${e(name)}`);
export const insertRoute = (body) => restJson("POST", `${base()}/global/routes`, { body });
export const deleteRoute = (name) => restJson("DELETE", `${base()}/global/routes/${e(name)}`);

// ── addresses ────────────────────────────────────────────────────────────
export async function listAllAddresses() {
  const r = await restJson("GET", `${base()}/aggregated/addresses`);
  return Object.entries(r.items || {}).flatMap(([scope, v]) => (v.addresses || []).map((a) => ({ ...a, _scope: scope })));
}
export const insertAddress = (scopePath, body) => restJson("POST", `${base()}/${scopePath}/addresses`, { body });
export const deleteAddress = (scopePath, name) => restJson("DELETE", `${base()}/${scopePath}/addresses/${e(name)}`);

export const REGIONS = [
  "us-central1", "us-east1", "us-east4", "us-west1",
  "europe-west1", "europe-west4", "asia-south1", "asia-southeast1", "asia-northeast1",
];

export const firewallProtoPorts = (f) => {
  const list = f.allowed || f.denied || [];
  if (!list.length) return "—";
  return list.map((p) => (p.ports?.length ? `${p.IPProtocol}:${p.ports.join(",")}` : p.IPProtocol)).join(", ");
};
export const firewallAction = (f) => (f.allowed ? "Allow" : "Deny");
export const firewallTargets = (f) => (f.targetTags?.length ? f.targetTags.join(", ") : "Apply to all");
export const firewallFilters = (f) => (f.sourceRanges?.length ? f.sourceRanges.join(", ") : (f.sourceTags?.length ? f.sourceTags.join(", ") : "—"));

export const routeNextHop = (r) => {
  if (r.nextHopGateway) return "Default internet gateway";
  if (r.nextHopInstance) return nameOf(r.nextHopInstance);
  if (r.nextHopIp) return r.nextHopIp;
  if (r.nextHopVpnTunnel) return nameOf(r.nextHopVpnTunnel);
  if (r.nextHopIlb) return nameOf(r.nextHopIlb);
  return "—";
};

// ── peerings ─────────────────────────────────────────────────────────────
export const addPeering = (name, peering) => restJson("POST", `${base()}/global/networks/${e(name)}/addPeering`, { body: { networkPeering: peering } });
export const removePeering = (name, peeringName) => restJson("POST", `${base()}/global/networks/${e(name)}/removePeering`, { body: { name: peeringName } });
export const peerStatus = (p) => (p.state === "ACTIVE" ? "Active" : "Inactive");

export const validName = (n, what = "Name") => {
  if (!n) return `${what} is required.`;
  if (!/^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$/.test(n)) return `${what} must start with a lowercase letter and contain only lowercase letters, numbers and hyphens.`;
  return null;
};

// ── connectivity tests (Network Intelligence Center, networkmanagement v1) ─────────────
const ctBase = () => `/v1/projects/${e(getProject())}/locations/global/connectivityTests`;
export async function listConnectivityTests() {
  const r = await restJson("GET", ctBase());
  return r.resources || [];
}
export const getConnectivityTest = (name) => restJson("GET", `${ctBase()}/${e(name)}`);
export async function insertConnectivityTest(testId, body) {
  const r = await restJson("POST", ctBase(), { query: { testId }, body });
  return r.response;
}
export async function rerunConnectivityTest(name) {
  const r = await restJson("POST", `${ctBase()}/${e(name)}:rerun`, { body: {} });
  return r.response;
}
export const deleteConnectivityTest = (name) => restJson("DELETE", `${ctBase()}/${e(name)}`);

export const ctId = (t) => nameOf(t.name);
export const endpointLabel = (ep) => (ep?.instance ? nameOf(ep.instance) : (ep?.ipAddress || "—"));
export const ctResult = (t) => t.reachabilityDetails?.result;

const CT_STATE_LABEL = {
  START_FROM_INSTANCE: "Initial state", START_FROM_INTERNET: "Initial state",
  APPLY_INGRESS_FIREWALL_RULE: "Ingress firewall", APPLY_EGRESS_FIREWALL_RULE: "Egress firewall",
  APPLY_ROUTE: "Route", NAT: "NAT", FORWARD: "Forward", DELIVER: "Deliver", DROP: "Drop",
};
export const ctStepLabel = (s) => CT_STATE_LABEL[s.state] || s.state;

// ── internal ranges (networkconnectivity.googleapis.com v1) ────────────────────────────
const ncBase = (loc = "global") => `/v1/projects/${e(getProject())}/locations/${e(loc)}/internalRanges`;
export async function listInternalRanges() {
  const r = await restJson("GET", ncBase());
  return r.internalRanges || [];
}
export async function insertInternalRange(body) {
  const r = await restJson("POST", ncBase(), { query: { internalRangeId: body.name }, body });
  return r.response;
}
export const deleteInternalRange = (name) => restJson("DELETE", `${ncBase()}/${e(name)}`);

// ── Serverless VPC Access connectors (vpcaccess.googleapis.com v1) ─────────────────────
const connectorsBase = (region) => `/v1/projects/${e(getProject())}/locations/${e(region)}/connectors`;
export async function listConnectors(region) {
  const r = await restJson("GET", connectorsBase(region));
  return r.connectors || [];
}
export async function listAllConnectors() {
  const lists = await Promise.all(REGIONS.map((r) => listConnectors(r).then((items) => items.map((c) => ({ ...c, _region: r }))).catch(() => [])));
  return lists.flat();
}
export async function insertConnector(region, body) {
  const r = await restJson("POST", connectorsBase(region), { query: { connectorId: body.name }, body });
  return r.response;
}
export const deleteConnector = (region, name) => restJson("DELETE", `${connectorsBase(region)}/${e(name)}`);

// ── Private Service Connection (servicenetworking.googleapis.com v1) ───────────────────
const pscBase = "/v1/services/servicenetworking.googleapis.com/connections";
export async function listPscConnections(networkName) {
  const r = await restJson("GET", pscBase, { query: { network: `projects/${e(getProject())}/global/networks/${e(networkName)}` } });
  return r.connections || [];
}
export async function createPscConnection(networkName, reservedPeeringRanges) {
  const r = await restJson("POST", pscBase, { body: { network: `projects/${getProject()}/global/networks/${networkName}`, reservedPeeringRanges } });
  return r.response;
}
export const deletePscConnection = (networkName) => restJson(
  "POST", `${pscBase}/servicenetworking.googleapis.com:deleteConnection`, { body: { network: `projects/${getProject()}/global/networks/${networkName}` } },
);
export const reservePeeringRange = (body) => restJson("POST", `${base()}/global/addresses`, {
  body: { ...body, purpose: "VPC_PEERING", addressType: "INTERNAL" },
});
export async function listPeeringRanges(networkName) {
  const all = await listAllAddresses();
  return all.filter((a) => a.purpose === "VPC_PEERING" && nameOf(a.network) === networkName);
}

// ── Shared VPC / XPN (compute.googleapis.com v1 projects.*) ────────────────────────────
export const enableXpnHost = () => restJson("POST", `${base()}/enableXpnHost`, { body: {} });
export const disableXpnHost = () => restJson("POST", `${base()}/disableXpnHost`, { body: {} });
export const enableXpnResource = (serviceProjectId) => restJson("POST", `${base()}/enableXpnResource`, { body: { xpnResource: { id: serviceProjectId, type: "PROJECT" } } });
export const disableXpnResource = (serviceProjectId) => restJson("POST", `${base()}/disableXpnResource`, { body: { xpnResource: { id: serviceProjectId, type: "PROJECT" } } });
export async function getXpnResources() {
  const r = await restJson("GET", `${base()}/getXpnResources`);
  return r.resources || [];
}
export async function listUsableSubnetworks() {
  const r = await restJson("GET", `${base()}/aggregated/usableSubnetworks`);
  return r.items || [];
}

// ── Network firewall policies (regional, compute.googleapis.com v1) ────────────────────
const nfpBase = (region) => `${base()}/regions/${e(region)}/firewallPolicies`;
export async function listFirewallPolicies(region) {
  const r = await restJson("GET", nfpBase(region));
  return r.items || [];
}
export async function listAllFirewallPolicies() {
  const lists = await Promise.all(REGIONS.map((r) => listFirewallPolicies(r).then((items) => items.map((p) => ({ ...p, _region: r }))).catch(() => [])));
  return lists.flat();
}
export const insertFirewallPolicy = (region, body) => restJson("POST", nfpBase(region), { body });
export const deleteFirewallPolicy = (region, name) => restJson("DELETE", `${nfpBase(region)}/${e(name)}`);
export const addPolicyRule = (region, name, rule) => restJson("POST", `${nfpBase(region)}/${e(name)}/addRule`, { body: { firewallPolicyRule: rule } });
export const addPolicyAssociation = (region, name, network) => restJson("POST", `${nfpBase(region)}/${e(name)}/addAssociation`, { body: { association: { name: `${network}-assoc`, attachmentTarget: network } } });

// ── Packet mirroring (regional, compute.googleapis.com v1) ─────────────────────────────
const pmBase = (region) => `${base()}/regions/${e(region)}/packetMirrorings`;
export async function listPacketMirrorings(region) {
  const r = await restJson("GET", pmBase(region));
  return r.items || [];
}
export async function listAllPacketMirrorings() {
  const lists = await Promise.all(REGIONS.map((r) => listPacketMirrorings(r).then((items) => items.map((p) => ({ ...p, _region: r }))).catch(() => [])));
  return lists.flat();
}
export const insertPacketMirroring = (region, body) => restJson("POST", pmBase(region), { body });
export const deletePacketMirroring = (region, name) => restJson("DELETE", `${pmBase(region)}/${e(name)}`);

// ── Cloud Logging read-back (real entries from netsim's per-packet counters, offline-only —
// empty unless VYOMI_NETSIM_ENFORCE is on and real traffic has crossed the enforcer) ────────
async function listLogEntries(logId) {
  const r = await restJson("POST", "/v2/entries:list", {
    body: { resourceNames: [`projects/${getProject()}`], filter: `logName="projects/${getProject()}/logs/${logId}"`, pageSize: 50 },
  });
  return r.entries || [];
}
export const listFlowLogEntries = () => listLogEntries("compute.googleapis.com%2Fvpc_flows");
export const listMirroredPacketLogEntries = () => listLogEntries("vyomi.dev%2Fpacket_mirroring");
