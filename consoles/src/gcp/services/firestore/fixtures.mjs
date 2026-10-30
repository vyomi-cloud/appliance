/* UI-conformance fixtures: create real resources over the native Firestore wire so the
 * "no statics" check (consoles/tests/ui-conformance.mjs) proves every list/detail page
 * renders live backend state, not hard-coded markup. */
const PROJECT = "vyomi-project";
const base = (db) => `/v1/projects/${PROJECT}/databases/${encodeURIComponent(db)}`;
const DB = "uic-firestore-db";

async function ensureDatabase(wire, db, locationId = "nam5") {
  try {
    await wire("POST", `/v1/projects/${PROJECT}/databases?databaseId=${encodeURIComponent(db)}`,
      { svc: null, body: { locationId, type: "FIRESTORE_NATIVE" } });
  } catch { /* already exists from an earlier page in this run */ }
  return db;
}

async function listBackups(wire, location = "nam5") {
  const r = await wire("GET", `/v1/projects/${PROJECT}/locations/${location}/backups`, { svc: null });
  return r.backups || [];
}

export default {
  /** Ensures the shared {resource-name} database used by every per-database page exists. */
  "firestore-database": (wire) => ensureDatabase(wire, DB),

  /** "databases" list page: create a uniquely named database and look for its id. */
  "live-database": async (wire, uniq) => {
    const id = `uic-${uniq}`.toLowerCase();
    await ensureDatabase(wire, id);
    return id;
  },

  /** "firestore-studio" detail page: a document in a uniquely named collection shows up
   *  in the Collections pane with no further navigation. */
  "live-studio-collection": async (wire, uniq) => {
    await ensureDatabase(wire, DB);
    await wire("POST", `${base(DB)}/documents/${uniq}`, { svc: null, query: { documentId: "d1" },
      body: { fields: { ping: { stringValue: "ok" } } } });
    return uniq;
  },

  /** "indexes" list page: a composite index on a uniquely named collection group. */
  "live-index": async (wire, uniq) => {
    await ensureDatabase(wire, DB);
    await wire("POST", `${base(DB)}/collectionGroups/${uniq}/indexes`, { svc: null,
      body: { queryScope: "COLLECTION", fields: [{ fieldPath: "name", order: "ASCENDING" }] } });
    return uniq;
  },

  /** "ttl" list page: a TTL policy on a uniquely named collection group. */
  "live-ttl": async (wire, uniq) => {
    await ensureDatabase(wire, DB);
    await wire("PATCH", `${base(DB)}/collectionGroups/${uniq}/fields/expiresAt`, { svc: null, body: { ttlConfig: {} } });
    return uniq;
  },

  /** "import-export" list page: an export naming a uniquely named collection. */
  "live-export": async (wire, uniq) => {
    await ensureDatabase(wire, DB);
    await wire("POST", `${base(DB)}:exportDocuments`, { svc: null,
      body: { collectionIds: [uniq], outputUriPrefix: "gs://uic-bucket/firestore-export" } });
    return uniq;
  },

  /** "disaster-recovery" list page: a backup schedule whose first tick fires an immediate
   *  backup; the new backup's id is the unique marker. */
  "live-backup": async (wire, uniq) => {
    await ensureDatabase(wire, DB);
    const before = new Set((await listBackups(wire)).map((b) => b.name));
    await wire("POST", `${base(DB)}/backupSchedules`, { svc: null, body: { retention: "604800s", dailyRecurrence: {} } });
    const after = await listBackups(wire);
    const fresh = after.find((b) => !before.has(b.name));
    return (fresh || after[0]).name.split("/").pop();
  },
};
