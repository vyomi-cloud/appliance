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
