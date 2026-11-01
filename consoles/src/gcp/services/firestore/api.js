/* Firestore over the NATIVE Firestore REST API v1 (the same wire the
 * google-cloud-firestore data client and the Firestore Admin REST calls use):
 * data plane at `.../databases/{db}/documents/...` and admin plane (databases,
 * indexes, fields/TTL, backups, operations, security rules) alongside it. */
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

const e = encodeURIComponent;
const encPath = (p) => p.split("/").filter(Boolean).map(e).join("/");
const dbBase = (db) => `/v1/projects/${getProject()}/databases/${e(db)}`;
const docsBase = (db, rel) => `${dbBase(db)}/documents${rel ? "/" + encPath(rel) : ""}`;

// ── Databases ────────────────────────────────────────────────────────────────────────────
export async function listDatabases() {
  const r = await restJson("GET", `/v1/projects/${getProject()}/databases`);
  return r.databases || [];
}
export const getDatabase = (db) => restJson("GET", dbBase(db));
export const createDatabase = (databaseId, body) =>
  restJson("POST", `/v1/projects/${getProject()}/databases`, { query: { databaseId }, body });
export const patchDatabase = (db, body) =>
  restJson("PATCH", dbBase(db), { query: { updateMask: Object.keys(body).join(",") }, body });
export const deleteDatabase = (db) => restJson("DELETE", dbBase(db));
export const restoreDatabase = (databaseId, backupName) =>
  restJson("POST", `/v1/projects/${getProject()}/databases:restore`, { body: { databaseId, backup: backupName } });

export const DB_LOCATIONS = [
  ["nam5", "nam5 (United States)"], ["eur3", "eur3 (Europe)"],
  ["us-central1", "us-central1 (Iowa)"], ["us-east1", "us-east1 (South Carolina)"],
  ["europe-west1", "europe-west1 (Belgium)"], ["asia-south1", "asia-south1 (Mumbai)"],
  ["asia-northeast1", "asia-northeast1 (Tokyo)"],
];
export const validDatabaseId = (id) => {
  if (id === "(default)") return null;
  if (!id) return "Database ID is required.";
  if (id.length < 4 || id.length > 63) return "Database IDs must contain 4-63 characters.";
  if (!/^[a-z0-9][a-z0-9-]*[a-z0-9]$/.test(id)) return "Use only lowercase letters, numbers and hyphens. Start and end with a letter or number.";
  return null;
};

// ── Documents (Firestore Studio data viewer) ────────────────────────────────────────────────
export async function listCollectionIds(db, parent = "") {
  const r = await restJson("POST", `${docsBase(db, parent)}:listCollectionIds`, { body: {} });
  return r.collectionIds || [];
}
export async function listDocuments(db, coll) {
  const r = await restJson("GET", docsBase(db, coll));
  return r.documents || [];
}
export const getDocument = (db, docPath, readTime) =>
  restJson("GET", docsBase(db, docPath), readTime ? { query: { readTime } } : {});
export const createDocument = (db, coll, fields, documentId) =>
  restJson("POST", docsBase(db, coll), { query: documentId ? { documentId } : {}, body: { fields } });
export const setDocument = (db, docPath, fields) =>
  restJson("PATCH", docsBase(db, docPath), { body: { fields } });
export const deleteDocument = (db, docPath) => restJson("DELETE", docsBase(db, docPath));

export async function runQuery(db, parent, structuredQuery) {
  const rows = await restJson("POST", `${docsBase(db, parent)}:runQuery`, { body: { structuredQuery } });
  return (Array.isArray(rows) ? rows : []).filter((r) => r.document).map((r) => r.document);
}

/** doc.name -> the path relative to .../documents/ (e.g. "users/alice"). */
export const docRelPath = (doc) => doc.name.split("/documents/")[1];
export const docId = (doc) => docRelPath(doc).split("/").pop();

export const FIELD_TYPES = ["string", "number", "boolean", "map", "array", "null", "timestamp", "geopoint", "reference", "vector"];
/** {name, type, value} rows (the Studio's "Start a collection"/"Add field" editor) -> typed `fields`. */
export function fieldsFromRows(rows) {
  const out = {};
  for (const r of rows) {
    if (!r.name) continue;
    out[r.name] = encodeValue(r.type, r.value);
  }
  return out;
}
export function encodeValue(type, value) {
  switch (type) {
    case "number": return Number(value) % 1 === 0 ? { integerValue: String(Number(value)) } : { doubleValue: Number(value) };
    case "boolean": return { booleanValue: value === true || value === "true" };
    case "null": return { nullValue: null };
    case "timestamp": return { timestampValue: value ? new Date(value).toISOString() : new Date().toISOString() };
    case "geopoint": { const [lat, lng] = String(value).split(",").map(Number); return { geoPointValue: { latitude: lat || 0, longitude: lng || 0 } }; }
    case "reference": return { referenceValue: value };
    case "map": return { mapValue: { fields: {} } };
    case "array": return { arrayValue: { values: [] } };
    // Vyomi's vector encoding matches the real SDK's Vector class wire shape: a mapValue
    // tagged `__type__: "__vector__"` carrying the components as an arrayValue of doubles.
    case "vector": return encodeVector(String(value).split(",").map((n) => Number(n.trim()) || 0));
    default: return { stringValue: String(value ?? "") };
  }
}
export const encodeVector = (values) => ({ mapValue: { fields: {
  __type__: { stringValue: "__vector__" },
  value: { arrayValue: { values: values.map((n) => ({ doubleValue: n })) } },
} } });
export const isVectorValue = (v) => v?.mapValue?.fields?.__type__?.stringValue === "__vector__" && v.mapValue.fields.value !== undefined;
export const vectorFloats = (v) => (v?.mapValue?.fields?.value?.arrayValue?.values || []).map((x) => Number(x.doubleValue ?? x.integerValue ?? 0));
/** A typed Firestore value -> a short display string for the data-viewer grid. */
export function displayValue(v) {
  if (!v || typeof v !== "object") return "";
  if (isVectorValue(v)) return `[${vectorFloats(v).join(", ")}]`;
  const [kind, val] = Object.entries(v)[0] || [];
  if (kind === "mapValue") return `{${Object.keys(val?.fields || {}).length} fields}`;
  if (kind === "arrayValue") return `[${(val?.values || []).length} items]`;
  if (kind === "geoPointValue") return `${val.latitude}, ${val.longitude}`;
  if (kind === "nullValue") return "null";
  if (kind === "booleanValue") return String(val);
  return String(val ?? "");
}
export const valueType = (v) => isVectorValue(v) ? "vector" : Object.keys(v || {})[0]?.replace(/Value$/, "").toLowerCase() || "string";

// ── Indexes ──────────────────────────────────────────────────────────────────────────────
export async function listIndexes(db, collectionGroup = "-") {
  const r = await restJson("GET", `${dbBase(db)}/collectionGroups/${e(collectionGroup)}/indexes`);
  return r.indexes || [];
}
export const createIndex = (db, collectionGroup, body) =>
  restJson("POST", `${dbBase(db)}/collectionGroups/${e(collectionGroup)}/indexes`, { body });
export const deleteIndex = (db, collectionGroup, indexId) =>
  restJson("DELETE", `${dbBase(db)}/collectionGroups/${e(collectionGroup)}/indexes/${e(indexId)}`);

// ── Fields / TTL / single-field exemptions ──────────────────────────────────────────────────
export async function listTtlPolicies(db) {
  const r = await restJson("GET", `${dbBase(db)}/collectionGroups/-/fields`, { query: { filter: "ttlConfig:*" } });
  return r.fields || [];
}
export const setFieldTtl = (db, collectionGroup, fieldPath, enabled) =>
  restJson("PATCH", `${dbBase(db)}/collectionGroups/${e(collectionGroup)}/fields/${e(fieldPath)}`, { body: { ttlConfig: enabled ? {} : null } });
export const ttlFieldOf = (f) => f.name.split("/fields/")[1];
export const ttlGroupOf = (f) => f.name.split("/collectionGroups/")[1].split("/fields/")[0];

export async function listFieldExemptions(db) {
  const r = await restJson("GET", `${dbBase(db)}/collectionGroups/-/fields`);
  return (r.fields || []).filter((f) => f.indexConfig?.indexes?.length);
}
export const setFieldExemption = (db, collectionGroup, fieldPath, indexes) =>
  restJson("PATCH", `${dbBase(db)}/collectionGroups/${e(collectionGroup)}/fields/${e(fieldPath)}`, { body: { indexConfig: { indexes, usesAncestorConfig: false } } });

// ── Backup schedules + backups (Disaster recovery) ──────────────────────────────────────────
export async function listBackupSchedules(db) {
  const r = await restJson("GET", `${dbBase(db)}/backupSchedules`);
  return r.backupSchedules || [];
}
export const createBackupSchedule = (db, body) => restJson("POST", `${dbBase(db)}/backupSchedules`, { body });
export const deleteBackupSchedule = (db, scheduleId) => restJson("DELETE", `${dbBase(db)}/backupSchedules/${e(scheduleId)}`);
export async function listBackups(location) {
  const r = await restJson("GET", `/v1/projects/${getProject()}/locations/${e(location)}/backups`);
  return r.backups || [];
}
export const deleteBackup = (location, backupId) =>
  restJson("DELETE", `/v1/projects/${getProject()}/locations/${e(location)}/backups/${e(backupId)}`);

// ── Import / Export ──────────────────────────────────────────────────────────────────────
export async function listOperations(db) {
  const r = await restJson("GET", `${dbBase(db)}/operations`);
  return r.operations || [];
}
export const exportDocuments = (db, body) => restJson("POST", `${dbBase(db)}:exportDocuments`, { body });
export const importDocuments = (db, body) => restJson("POST", `${dbBase(db)}:importDocuments`, { body });

// ── Usage (real running totals, no time-series) ─────────────────────────────────────────────
export const getUsage = (db) => restJson("GET", `${dbBase(db)}:usage`);

// ── Security rules ───────────────────────────────────────────────────────────────────────
export async function getSecurityRules(db) {
  const r = await restJson("POST", `${dbBase(db)}:getSecurityRules`, { body: {} });
  return r.rules || "";
}
export const updateSecurityRules = (db, rules) => restJson("POST", `${dbBase(db)}:updateSecurityRules`, { body: { rules } });
/** Development & test (Rules Playground): really parses + evaluates `rules` against one
 * simulated request. `request.resourceData` / `requestResourceData` are plain JSON (not
 * Firestore's typed wire encoding) — the same shape a person fills into the form. */
export const testSecurityRules = (db, body) => restJson("POST", `${dbBase(db)}:testSecurityRules`, { body });

// ── Insights (real query/index telemetry) ───────────────────────────────────────────────
export const getInsights = (db) => restJson("GET", `${dbBase(db)}:insights`);

// ── Key Visualizer (real per-document access heatmap) ───────────────────────────────────
export const getKeyVisualizer = (db) => restJson("GET", `${dbBase(db)}:keyVisualizer`);

export const DEFAULT_RULES = `rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if false;
    }
  }
}`;
