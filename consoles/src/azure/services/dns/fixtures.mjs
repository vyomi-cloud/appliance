/* UI-conformance fixtures for DNS zones (ARM control plane — zones, record sets, locks,
 * virtual network links). See storage/fixtures.mjs for the pattern this follows. */
const SUB = "00000000-0000-0000-0000-cloudlearn01";
const RG = "uic-rg";
const ZONE = "uic-dns-zone.com";
const API_VERSION = "2018-05-01";
const zonePath = (name) => `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/dnszones/${encodeURIComponent(name)}`;

async function ensureZone(wire, name = ZONE, properties = {}) {
  await wire("PUT", `${zonePath(name)}?api-version=${API_VERSION}`, { svc: null, body: { location: "global", properties: { zoneType: "Public", ...properties } } }).catch(() => {});
}
const lockUrl = (name, lockName) => `${zonePath(name)}/providers/Microsoft.Authorization/locks/${encodeURIComponent(lockName)}?api-version=2020-05-01`;

export default {
  "az-dns-zone": async (wire) => { await ensureZone(wire); },

  // Each of these mints a FRESH zone named after `uniq` (not the shared "uic-dns-zone.com") so
  // the page — routed at "#/dns/uic-rg/{live}/…" — resolves {resource-name} to the same string
  // the liveness check searches for.
  "live-zone": async (wire, uniq) => {
    const name = `${uniq}.com`;
    await ensureZone(wire, name);
    return name;
  },

  // A lock write on the zone is a real ARM mutation, so it lands on the unified
  // Microsoft.Insights/eventtypes feed (core/azure_arm_core.py) — the lock NAME becomes the
  // activity entry's "detail", so it is the uniquely-named thing to look for.
  "live-activity": async (wire, uniq) => {
    const name = `${uniq}.com`;
    await ensureZone(wire, name);
    await wire("PUT", lockUrl(name, uniq), { svc: null, body: { properties: { level: "ReadOnly", notes: "uic" } } });
    return name;
  },

  "live-lock": async (wire, uniq) => {
    const name = `${uniq}.com`;
    await ensureZone(wire, name);
    await wire("PUT", lockUrl(name, uniq), { svc: null, body: { properties: { level: "CanNotDelete", notes: "uic" } } });
    return name;
  },

  // A private zone with a registration virtual network link — a real nested PATCH on the
  // zone's own properties (azure.dns.vnet_links), scoped to a fresh zone+vnet pair.
  "live-vnetlink": async (wire, uniq) => {
    const name = `${uniq}.priv`;
    await ensureZone(wire, name, { zoneType: "Private" });
    const vnetId = `/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.Network/virtualNetworks/${uniq}-vnet`;
    await wire("PATCH", `${zonePath(name)}?api-version=${API_VERSION}`, { svc: null, body: { properties: { registrationVirtualNetworks: [{ id: vnetId }] } } });
    return name;
  },
};
