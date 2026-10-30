/* SQL databases over the native Azure wire.
 *   Control plane: ARM  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Sql/servers/{server}
 *                       .../servers/{server}/databases/{db}, .../servers/{server}/firewallRules/{rule}
 *   Data plane:    a small REST/JSON wire at /azure-sql/servers/{server}/databases/{db}/query
 *                  (core/azure_sql_core.py) that runs REAL SQL (sqlite in Nano) — the Query
 *                  editor and the "Sample" data option use it. ARM metadata and the data-plane
 *                  SqlStore are separate stores, so `ensureDataPlane` bridges them: it registers
 *                  the server/database (idempotent) before any query runs, regardless of
 *                  whether the database was created through the wizard or over the wire.
 *
 * The ARM core's generic list only filters by type + subscription (not by the server segment
 * in the path), so "list databases under server X" actually returns every database in the
 * subscription. `dbFields` re-derives the true {resourceGroup, server, name} from each record's
 * OWN id instead of trusting the call's arguments — that turns the quirk into a correct
 * cross-server aggregate for the subscription-wide "SQL databases" browse grid.
 */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

export const API_VERSION = "2023-08-01";
const LOCK_API_VERSION = "2020-05-01";

export const ServersArm = armType("Microsoft.Sql", "servers", API_VERSION);

const serverPath = (rg, server) => ServersArm.path(rg, server);
const dbPath = (rg, server, db) => `${serverPath(rg, server)}/databases/${encodeURIComponent(db)}`;
const fwPath = (rg, server, rule) => `${serverPath(rg, server)}/firewallRules/${encodeURIComponent(rule)}`;

const shapeServer = (s) => ({ ...s, resourceGroup: parseId(s.id).resourceGroup });

export const listServers = async () => (await ServersArm.list()).map(shapeServer);
export const getServer = async (rg, name) => shapeServer(await ServersArm.get(rg, name));
export const createServer = (rg, name, body) => ServersArm.put(rg, name, body);
export const updateServer = (rg, name, body) => ServersArm.patch(rg, name, body);
export const deleteServer = (rg, name) => ServersArm.remove(rg, name);

/** {resourceGroup, server, name} re-derived from a database record's own resource id. */
function dbFields(d) {
  const m = /\/resourceGroups\/([^/]+)\/providers\/Microsoft\.Sql\/servers\/([^/]+)\/databases\/([^/]+)$/i.exec(d.id || "");
  return { resourceGroup: m?.[1] || "", server: m?.[2] || "", name: m?.[3] || d.name };
}
const shapeDb = (d) => ({ ...d, ...dbFields(d) });

async function listDatabasesRaw(rg, server) {
  const r = await restJson("GET", `${serverPath(rg, server)}/databases`, { query: { "api-version": API_VERSION } });
  return (r.value || []).map(shapeDb);
}

/** Every database across every server in the subscription (the "SQL databases" browse grid). */
export async function listAllDatabases() {
  const servers = await listServers();
  const lists = await Promise.all(servers.map((s) => listDatabasesRaw(s.resourceGroup, s.name).catch(() => [])));
  const byId = new Map();
  for (const l of lists) for (const d of l) byId.set(d.id, d);
  return [...byId.values()];
}

export const getDatabase = async (rg, server, name) => shapeDb(await restJson("GET", dbPath(rg, server, name), { query: { "api-version": API_VERSION } }));
export const createDatabase = (rg, server, name, body) => restJson("PUT", dbPath(rg, server, name), { query: { "api-version": API_VERSION }, body });
export const updateDatabase = (rg, server, name, body) => restJson("PATCH", dbPath(rg, server, name), { query: { "api-version": API_VERSION }, body });
export const deleteDatabase = (rg, server, name) => restJson("DELETE", dbPath(rg, server, name), { query: { "api-version": API_VERSION } });

// ── Firewall rules (Microsoft.Sql/servers/firewallRules) ───────────────────────────────
export async function listFirewallRules(rg, server) {
  const r = await restJson("GET", `${serverPath(rg, server)}/firewallRules`, { query: { "api-version": API_VERSION } });
  const mine = new RegExp(`/servers/${server}/firewallRules/([^/]+)$`, "i");
  return (r.value || []).filter((x) => mine.test(x.id)).map((x) => ({ ...x, name: mine.exec(x.id)[1] }));
}
export const putFirewallRule = (rg, server, rule, body) => restJson("PUT", fwPath(rg, server, rule), { query: { "api-version": API_VERSION }, body });
export const deleteFirewallRule = (rg, server, rule) => restJson("DELETE", fwPath(rg, server, rule), { query: { "api-version": API_VERSION } });

// ── Locks (Microsoft.Authorization/locks, resource-scoped extension resource) ──────────
const lockPath = (resPath, lockName) => `${resPath}/providers/Microsoft.Authorization/locks${lockName ? `/${encodeURIComponent(lockName)}` : ""}`;
export const listLocks = async (resPath) => (await restJson("GET", lockPath(resPath), { query: { "api-version": LOCK_API_VERSION } })).value || [];
export const putLock = (resPath, lockName, body) => restJson("PUT", lockPath(resPath, lockName), { query: { "api-version": LOCK_API_VERSION }, body });
export const deleteLock = (resPath, lockName) => restJson("DELETE", lockPath(resPath, lockName), { query: { "api-version": LOCK_API_VERSION } });
export const databasePath = dbPath;
export const serverResourcePath = serverPath;

// ── Activity log (Microsoft.Insights/eventtypes/management/values, filtered to a resource) ──
export const listActivityLog = async (resPath) => {
  const query = { "api-version": "2015-04-01", "$filter": `resourceUri eq '${resPath}'` };
  return (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Insights/eventtypes/management/values`, { query })).value || [];
};

// ── Data plane (core/azure_sql_core.py, real SQL via SqlStore) ─────────────────────────
const sqlWire = (method, path, opts) => restJson(method, `/azure-sql${path}`, opts);

/** Idempotently register server+database in the SqlStore so queries have somewhere to run,
 *  regardless of whether the database was created through the ARM wizard or over the wire. */
export async function ensureDataPlane(server, db) {
  await sqlWire("PUT", `/servers/${encodeURIComponent(server)}`, {});
  await sqlWire("PUT", `/servers/${encodeURIComponent(server)}/databases/${encodeURIComponent(db)}`, {});
}
export const dropDataPlane = (server, db) =>
  sqlWire("DELETE", `/servers/${encodeURIComponent(server)}/databases/${encodeURIComponent(db)}`, {}).catch(() => {});
export const runQuery = (server, db, sql, params) =>
  sqlWire("POST", `/servers/${encodeURIComponent(server)}/databases/${encodeURIComponent(db)}/query`, { body: { sql, params } });

export const listTables = (server, db) =>
  runQuery(server, db, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name");
export const listViews = (server, db) =>
  runQuery(server, db, "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name");

const SAMPLE_SCRIPT = [
  "CREATE TABLE Customer (CustomerID INTEGER PRIMARY KEY, FirstName TEXT, LastName TEXT, CompanyName TEXT, EmailAddress TEXT)",
  "CREATE TABLE Product (ProductID INTEGER PRIMARY KEY, Name TEXT, ProductCategory TEXT, ListPrice REAL)",
  "CREATE TABLE SalesOrderHeader (SalesOrderID INTEGER PRIMARY KEY, OrderDate TEXT, CustomerID INTEGER, TotalDue REAL)",
  "INSERT INTO Customer (FirstName, LastName, CompanyName, EmailAddress) VALUES ('Orlando', 'Gee', 'A Bike Store', 'orlando0@adventure-works.com')",
  "INSERT INTO Customer (FirstName, LastName, CompanyName, EmailAddress) VALUES ('Keith', 'Harris', 'Progressive Sports', 'keith0@adventure-works.com')",
  "INSERT INTO Product (Name, ProductCategory, ListPrice) VALUES ('Mountain-100 Silver, 38', 'Mountain Bikes', 3399.99)",
  "INSERT INTO Product (Name, ProductCategory, ListPrice) VALUES ('Road-150 Red, 62', 'Road Bikes', 3578.27)",
  "INSERT INTO SalesOrderHeader (OrderDate, CustomerID, TotalDue) VALUES ('2026-01-15', 1, 3756.99)",
  "INSERT INTO SalesOrderHeader (OrderDate, CustomerID, TotalDue) VALUES ('2026-02-02', 2, 3953.99)",
];
export async function loadSampleData(server, db) {
  for (const sql of SAMPLE_SCRIPT) await runQuery(server, db, sql);
}

// ── Display-only helpers (no backend call) ──────────────────────────────────────────────
export const serverFqdn = (server) => `${server}.database.windows.net`;

export function connectionStrings(server, db) {
  const fqdn = serverFqdn(server);
  return {
    "ADO.NET": {
      sql: `Server=tcp:${fqdn},1433;Initial Catalog=${db};Persist Security Info=False;User ID=<username>;Password=<password>;MultipleActiveResultSets=False;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;`,
      entra: `Server=tcp:${fqdn},1433;Initial Catalog=${db};Authentication=Active Directory Default;Encrypt=True;TrustServerCertificate=False;Connection Timeout=30;`,
    },
    JDBC: {
      sql: `jdbc:sqlserver://${fqdn}:1433;database=${db};user=<username>@${server};password=<password>;encrypt=true;trustServerCertificate=false;`,
      entra: `jdbc:sqlserver://${fqdn}:1433;database=${db};authentication=ActiveDirectoryDefault;encrypt=true;trustServerCertificate=false;`,
    },
    ODBC: {
      sql: `Driver={ODBC Driver 18 for SQL Server};Server=tcp:${fqdn},1433;Database=${db};Uid=<username>;Pwd=<password>;Encrypt=yes;TrustServerCertificate=no;`,
      entra: `Driver={ODBC Driver 18 for SQL Server};Server=tcp:${fqdn},1433;Database=${db};Authentication=ActiveDirectoryDefault;Encrypt=yes;TrustServerCertificate=no;`,
    },
    PHP: {
      sql: `$connectionOptions = ["UID" => "<username>", "PWD" => "<password>", "Database" => "${db}", "Encrypt" => true];\n$serverName = "tcp:${fqdn},1433";\n$conn = sqlsrv_connect($serverName, $connectionOptions);`,
      entra: `// PHP: Microsoft Entra passwordless authentication is not supported by the sqlsrv driver.`,
    },
    Go: {
      sql: `sql.Open("sqlserver", "server=${fqdn};user id=<username>;password=<password>;database=${db};")`,
      entra: `sql.Open("sqlserver", "server=${fqdn};database=${db};fedauth=ActiveDirectoryDefault;")`,
    },
  };
}

/** A rough, deterministic client-side estimate (the real portal's figure comes from the
 *  Retail Prices API, which Vyomi does not simulate). */
export function estimateMonthlyCost({ tier, serverless, maxVCores, minVCores }) {
  const rate = { GeneralPurpose: 0.52, Hyperscale: 0.65, BusinessCritical: 1.33 }[tier] || 0.52;
  const vcores = serverless ? (Number(minVCores) + Number(maxVCores)) / 2 : Number(maxVCores);
  return Math.round(rate * vcores * 730 * 100) / 100;
}

export const SERVICE_TIERS = [
  { value: "GeneralPurpose", label: "General Purpose (Most budget-friendly, serverless compute)", vcore: true, serverless: true },
  { value: "Hyperscale", label: "Hyperscale (On-demand scalable storage)", vcore: true, serverless: false },
  { value: "BusinessCritical", label: "Business Critical (High transaction rate and high resiliency)", vcore: true, serverless: false },
  { value: "Basic", label: "Basic (For less demanding workloads)", vcore: false, dtu: { name: "Basic", tier: "Basic", capacity: 5 } },
  { value: "Standard", label: "Standard (For workloads with typical performance requirements)", vcore: false, dtu: { name: "S0", tier: "Standard", capacity: 10 } },
  { value: "Premium", label: "Premium (For IO-intensive workloads)", vcore: false, dtu: { name: "P1", tier: "Premium", capacity: 125 } },
];

/** Compute+storage form model → ARM {sku, properties} body (merged into the database record). */
export function computeStorageBody(f) {
  const t = SERVICE_TIERS.find((x) => x.value === f.tier) || SERVICE_TIERS[0];
  const sku = t.vcore
    ? { name: `${f.tier === "GeneralPurpose" ? "GP" : f.tier === "Hyperscale" ? "HS" : "BC"}${f.serverless ? "_S" : ""}_Gen5`, tier: f.tier, family: "Gen5", capacity: Number(f.maxVCores) }
    : { name: t.dtu.name, tier: t.dtu.tier, capacity: t.dtu.capacity };
  const autoPauseDelay = t.vcore && f.serverless ? (f.autoPause ? Number(f.days) * 1440 + Number(f.hours) * 60 + Number(f.minutes) : -1) : -1;
  return {
    sku,
    properties: {
      maxSizeBytes: Math.round(Number(f.dataMaxSizeGb) * 1024 * 1024 * 1024),
      zoneRedundant: !!f.zoneRedundant,
      ...(t.vcore ? { minCapacity: f.serverless ? Number(f.minVCores) : Number(f.maxVCores), autoPauseDelay } : {}),
    },
  };
}
