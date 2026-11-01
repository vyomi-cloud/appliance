/* Azure DNS zones over the native ARM wire: Microsoft.Network/dnszones (public AND private —
 * Vyomi models both under the one resource type, distinguished by properties.zoneType, matching
 * core/azure_dns_core.py) and their record sets (Microsoft.Network/dnszones/{type}/{name}).
 * az network dns zone|record-set ... and azure-mgmt-dns/armdns see the same resources. */
import { restJson } from "../../../common/wire.js";
import { getSubscription } from "../../kit/arm.js";

export const API_VERSION = "2018-05-01";
const LOCK_API_VERSION = "2020-05-01";

const sub = (s = getSubscription()) => `/subscriptions/${s}`;
export const zonePath = (rg, name) => `${sub()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.Network/dnszones/${encodeURIComponent(name)}`;

export const listZones = async (rg) =>
  (await restJson("GET", rg ? `${sub()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.Network/dnszones` : `${sub()}/providers/Microsoft.Network/dnszones`,
    { query: { "api-version": API_VERSION } })).value || [];
export const getZone = (rg, name) => restJson("GET", zonePath(rg, name), { query: { "api-version": API_VERSION } });
export const createZone = (rg, name, body) => restJson("PUT", zonePath(rg, name), { query: { "api-version": API_VERSION }, body });
export const updateZone = (rg, name, body) => restJson("PATCH", zonePath(rg, name), { query: { "api-version": API_VERSION }, body });
export const deleteZone = (rg, name) => restJson("DELETE", zonePath(rg, name), { query: { "api-version": API_VERSION } });

// ── Record sets ─────────────────────────────────────────────────────────────────────────
// Types the portal's own Add/Edit record set dialog offers (SOA is zone-managed; DS/NAPTR/TLSA
// round-trip over the API/CLI only, matching real Azure's own portal limitation).
export const RECORD_TYPES = ["A", "AAAA", "CAA", "CNAME", "MX", "NS", "PTR", "SRV", "TXT"];
export const ARM_FIELD = { A: "ARecords", AAAA: "AAAARecords", CAA: "caaRecords", CNAME: "CNAMERecord", MX: "MXRecords", NS: "NSRecords", PTR: "PTRRecords", SOA: "SOARecord", SRV: "SRVRecords", TXT: "TXTRecords" };
const FIELD = ARM_FIELD;
export const ALIASABLE = ["A", "AAAA", "CNAME"];

/** Per-type sub-fields the Add/Edit record set dialog collects, one row per record
 *  (CNAME/SOA hold a single record object, not a list). */
export const RECORD_FIELDS = {
  A: { multi: true, fields: [{ key: "ipv4Address", label: "IP address" }] },
  AAAA: { multi: true, fields: [{ key: "ipv6Address", label: "IP address" }] },
  CNAME: { multi: false, fields: [{ key: "cname", label: "Fully qualified domain name (FQDN)" }] },
  MX: { multi: true, fields: [{ key: "preference", label: "Priority", type: "number" }, { key: "exchange", label: "Mail exchange server" }] },
  NS: { multi: true, fields: [{ key: "nsdname", label: "Name server" }] },
  PTR: { multi: true, fields: [{ key: "ptrdname", label: "Domain name" }] },
  SRV: { multi: true, fields: [{ key: "priority", label: "Priority", type: "number" }, { key: "weight", label: "Weight", type: "number" }, { key: "port", label: "Port", type: "number" }, { key: "target", label: "Target" }] },
  TXT: { multi: true, fields: [{ key: "value", label: "Value" }] },
  CAA: { multi: true, fields: [{ key: "flags", label: "Flags", type: "number" }, { key: "tag", label: "Tag", options: ["issue", "issuewild", "iodef"] }, { key: "value", label: "Value" }] },
};

export const listRecordSets = async (rg, zone) =>
  (await restJson("GET", `${zonePath(rg, zone)}/all`, { query: { "api-version": API_VERSION } })).value || [];
export const getRecordSet = (rg, zone, type, name) => restJson("GET", `${zonePath(rg, zone)}/${type}/${encodeURIComponent(name)}`, { query: { "api-version": API_VERSION } });
export const putRecordSet = (rg, zone, type, name, body) => restJson("PUT", `${zonePath(rg, zone)}/${type}/${encodeURIComponent(name)}`, { query: { "api-version": API_VERSION }, body });
export const deleteRecordSet = (rg, zone, type, name) => restJson("DELETE", `${zonePath(rg, zone)}/${type}/${encodeURIComponent(name)}`, { query: { "api-version": API_VERSION } });

export const recordSetType = (rs) => (rs.type || "").split("/").pop();

/** Build a TXT-safe readable string for one record of `type`, used by both the Value
 *  column and the Edit dialog's row prefill. */
function one(type, r) {
  if (!r) return "";
  switch (type) {
    case "A": return r.ipv4Address;
    case "AAAA": return r.ipv6Address;
    case "CNAME": return r.cname;
    case "MX": return `${r.preference} ${r.exchange}`;
    case "NS": return r.nsdname;
    case "PTR": return r.ptrdname;
    case "SRV": return `${r.priority} ${r.weight} ${r.port} ${r.target}`;
    case "TXT": return (r.value || []).join("");
    case "CAA": return `${r.flags} ${r.tag} "${r.value}"`;
    case "SOA": return r.host;
    default: return JSON.stringify(r);
  }
}

/** The record set's "Value" column, matching the real portal's one-line summary. */
export function recordSetValue(rs) {
  const p = rs.properties || {};
  if (p.targetResource?.id) return `Alias to ${p.targetResource.id}`;
  const type = recordSetType(rs);
  const field = FIELD[type];
  const v = p[field];
  if (v === undefined || v === null) return "--";
  if (Array.isArray(v)) return v.map((r) => one(type, r)).join(", ") || "--";
  return one(type, v);
}

/** Record rows for the Edit dialog: one row of sub-field strings per record. */
export function recordSetRows(rs) {
  const p = rs.properties || {};
  const type = recordSetType(rs);
  const field = FIELD[type];
  const v = p[field];
  if (v === undefined || v === null) return [];
  const spec = RECORD_FIELDS[type];
  const toRow = (r) => Object.fromEntries(spec.fields.map((f) => [f.key, f.key === "value" && Array.isArray(r.value) ? r.value.join("") : String(r[f.key] ?? "")]));
  return spec.multi ? (v || []).map(toRow) : [toRow(v)];
}

/** rows (per RECORD_FIELDS[type]) → the ARM `properties.<Field>` shape for a PUT. */
export function rowsToArmField(type, rows) {
  const spec = RECORD_FIELDS[type];
  const toRecord = (row) => Object.fromEntries(spec.fields.map((f) => [f.key, f.key === "value" ? [String(row.value ?? "")] : (f.type === "number" ? Number(row[f.key]) : row[f.key])]));
  const records = rows.map(toRecord);
  return spec.multi ? records : (records[0] || {});
}

// ── Locks (Microsoft.Authorization/locks, extension resource on the zone) ──────────────
const lockPath = (rg, name, lockName) => `${zonePath(rg, name)}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;
export const listLocks = async (rg, name) => (await restJson("GET", lockPath(rg, name), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (rg, name, lockName, body) => restJson("PUT", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (rg, name, lockName) => restJson("DELETE", lockPath(rg, name, lockName), { query: { "api-version": LOCK_API_VERSION } });

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to this zone) ──
export const listActivityLog = async (rg, name) => {
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${zonePath(rg, name)}'` };
  return (await restJson("GET", `${sub()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Virtual networks (for the Virtual network links picker — Microsoft.Network/virtualNetworks) ──
export const listVirtualNetworks = async () =>
  (await restJson("GET", `${sub()}/providers/Microsoft.Network/virtualNetworks`, { query: { "api-version": "2023-09-01" } })).value || [];

export function toArmBody(f) {
  const props = { zoneType: f.zoneType };
  if (f.zoneType === "Private") {
    props.registrationVirtualNetworks = [];
    props.resolutionVirtualNetworks = [];
  }
  return { location: "global", tags: Object.fromEntries(f.tags.filter((t) => t.name).map((t) => [t.name, t.value])), properties: props };
}
