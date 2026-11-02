/* S3 sweep S3-3 native-wire calls: S3 Tables (service s3tables, rest-json), Storage Lens (s3control restXml),
 * and the Vyomi-internal access-analysis / dashboard-data routes (JSON under /v20180820/_vyomi). */
import { asList, authHeader, awsRest, s3, WIRE_BASE, WireError } from "../../../common/wire.js";
import { putAccountPab } from "./sweepApi.js";

const esc = (s) => String(s).replace(/[<>&'"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[c]));
const ACCOUNT = "123456789012";
const CTL_NS = 'xmlns="http://awss3control.amazonaws.com/doc/2016-08-20/"';
const ACCT = (method, path, opts = {}) => s3(method, `/v20180820/${path}`, { ...opts, headers: { "x-amz-account-id": ACCOUNT, ...(opts.headers || {}) } });

// ───────────────────────────── S3 Tables ─────────────────────────────
const TB = (method, path, opts = {}) => awsRest("s3tables", method, path, opts);
const arnPath = (arn) => encodeURIComponent(arn);
export const tableBucketArn = (name) => `arn:aws:s3tables:us-east-1:${ACCOUNT}:bucket/${name}`;

export async function listTableBuckets() {
  const out = []; let token;
  do {
    const r = await TB("GET", "/buckets", { query: { continuationToken: token } });
    out.push(...(r.tableBuckets || [])); token = r.continuationToken;
  } while (token);
  return out;
}
export const createTableBucket = (name, encryption) => TB("PUT", "/buckets", { body: { name, ...(encryption ? { encryptionConfiguration: encryption } : {}) } });
export const deleteTableBucket = (arn) => TB("DELETE", `/buckets/${arnPath(arn)}`);
export async function getTableBucketDetail(arn) {
  const [info, enc, maint, sc] = await Promise.all([
    TB("GET", `/buckets/${arnPath(arn)}`),
    TB("GET", `/buckets/${arnPath(arn)}/encryption`),
    TB("GET", `/buckets/${arnPath(arn)}/maintenance`),
    TB("GET", `/buckets/${arnPath(arn)}/storage-class`),
  ]);
  let policy = "";
  try { policy = (await TB("GET", `/buckets/${arnPath(arn)}/policy`)).resourcePolicy || ""; } catch (e) { if (e.status !== 404) throw e; }
  const tags = (await TB("GET", `/tag/${arnPath(arn)}`)).tags || {};
  return { ...info, encryption: enc.encryptionConfiguration, maintenance: maint.configuration, storageClass: sc.storageClassConfiguration?.storageClass, policy, tags };
}
export const putTableBucketPolicy = (arn, doc) => TB("PUT", `/buckets/${arnPath(arn)}/policy`, { body: { resourcePolicy: doc } });
export const deleteTableBucketPolicy = (arn) => TB("DELETE", `/buckets/${arnPath(arn)}/policy`);
export const putTableBucketEncryption = (arn, cfg) => TB("PUT", `/buckets/${arnPath(arn)}/encryption`, { body: { encryptionConfiguration: cfg } });
export const putTableBucketMaintenance = (arn, value) => TB("PUT", `/buckets/${arnPath(arn)}/maintenance/icebergUnreferencedFileRemoval`, { body: { value } });
export async function listNamespaces(arn) {
  const r = await TB("GET", `/namespaces/${arnPath(arn)}`);
  return (r.namespaces || []).map((n) => ({ name: (n.namespace || [])[0], id: n.namespaceId, created: n.createdAt }));
}
export const createNamespace = (arn, name) => TB("PUT", `/namespaces/${arnPath(arn)}`, { body: { namespace: [name] } });
export const deleteNamespace = (arn, name) => TB("DELETE", `/namespaces/${arnPath(arn)}/${name}`);
export async function listTables(arn) {
  const r = await TB("GET", `/tables/${arnPath(arn)}`);
  return (r.tables || []).map((t) => ({ name: t.name, namespace: (t.namespace || [])[0], arn: t.tableARN, created: t.createdAt, modified: t.modifiedAt, type: t.type }));
}
export async function createTable(arn, namespace, name, fields) {
  const metadata = fields.length ? { iceberg: { schema: { fields } } } : undefined;
  return TB("PUT", `/tables/${arnPath(arn)}/${namespace}`, { body: { name, format: "ICEBERG", ...(metadata ? { metadata } : {}) } });
}
export const deleteTable = (arn, ns, name) => TB("DELETE", `/tables/${arnPath(arn)}/${ns}/${name}`);
export async function getTableDetail(bucketArn, ns, name) {
  const t = await TB("GET", "/get-table", { query: { tableBucketARN: bucketArn, namespace: ns, name } });
  const base = `/tables/${arnPath(bucketArn)}/${ns}/${name}`;
  const maint = await TB("GET", `${base}/maintenance`);
  let policy = "";
  try { policy = (await TB("GET", `${base}/policy`)).resourcePolicy || ""; } catch (e) { if (e.status !== 404) throw e; }
  return { ...t, maintenance: maint.configuration, policy };
}
export const putTablePolicy = (bucketArn, ns, name, doc) => TB("PUT", `/tables/${arnPath(bucketArn)}/${ns}/${name}/policy`, { body: { resourcePolicy: doc } });
export const deleteTablePolicy = (bucketArn, ns, name) => TB("DELETE", `/tables/${arnPath(bucketArn)}/${ns}/${name}/policy`);
export async function listTableFiles(warehouse) {
  const bucket = String(warehouse || "").replace("s3://", "");
  if (!bucket) return [];
  const r = await s3("GET", `/${bucket}`, { query: { "list-type": "2" } });
  return asList(r.ListBucketResult?.Contents).map((o) => ({ key: o.Key, size: Number(o.Size || 0), modified: o.LastModified }));
}
export const uploadTableFile = (warehouse, key, body) => s3("PUT", `/${String(warehouse).replace("s3://", "")}/${key.split("/").map(encodeURIComponent).join("/")}`, { body });

// ───────────────────────────── Vyomi-internal JSON routes ─────────────────────────────
async function vy(method, path, query) {
  const qs = query ? "?" + new URLSearchParams(Object.entries(query).filter(([, v]) => v)).toString() : "";
  const res = await fetch(`${WIRE_BASE}/v20180820/_vyomi/${path}${qs}`, { method, headers: { ...authHeader("s3"), "x-amz-account-id": ACCOUNT } });
  const text = await res.text();
  let data = {}; try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text }; }
  if (!res.ok) throw new WireError(res.status, data.error, data.message, text);
  return data;
}
export const accessAnalysis = () => vy("GET", "access-analysis");
export const archiveFinding = (id) => vy("PUT", `access-analysis/findings/${id}/archive`);
export const unarchiveFinding = (id) => vy("PUT", `access-analysis/findings/${id}/unarchive`);
export const lensData = (id, { group, topN } = {}) => vy("GET", `storage-lens/${encodeURIComponent(id)}`, { group, topN });
export { putAccountPab };

// ───────────────────────────── Storage Lens ─────────────────────────────
export const DEFAULT_DASHBOARD = "default-account-dashboard";
export const lensArn = (id) => `arn:aws:s3:us-east-1:${ACCOUNT}:storage-lens/${id}`;
export const groupArn = (name) => `arn:aws:s3:us-east-1:${ACCOUNT}:storage-lens-group/${name}`;

export async function listLensConfigs() {
  const r = await ACCT("GET", "storagelens");
  return asList(r.ListStorageLensConfigurationsResult?.StorageLensConfiguration).map((c) => ({ id: c.Id, arn: c.StorageLensArn, region: c.HomeRegion, enabled: String(c.IsEnabled) === "true" }));
}
export async function getLensConfig(id) {
  const c = (await ACCT("GET", `storagelens/${encodeURIComponent(id)}`)).StorageLensConfiguration || {};
  const sc = c.AccountLevel?.BucketLevel?.PrefixLevel?.StorageMetrics;
  return {
    id: c.Id, enabled: String(c.IsEnabled) === "true", arn: c.StorageLensArn,
    include: asList(c.Include?.Buckets?.Arn).map((a) => a.replace("arn:aws:s3:::", "")),
    exclude: asList(c.Exclude?.Buckets?.Arn).map((a) => a.replace("arn:aws:s3:::", "")),
    prefixEnabled: String(sc?.IsEnabled) === "true",
    delimiter: sc?.SelectionCriteria?.Delimiter || "/", maxDepth: Number(sc?.SelectionCriteria?.MaxDepth || 10),
    minPct: sc?.SelectionCriteria?.MinStorageBytesPercentage ? Number(sc.SelectionCriteria.MinStorageBytesPercentage) : 1,
    groups: asList(c.AccountLevel?.StorageLensGroupLevel?.SelectionCriteria?.Include?.Arn).map((a) => a.split("/").pop()),
  };
}
export async function getLensTags(id) {
  return asList((await ACCT("GET", `storagelens/${encodeURIComponent(id)}/tagging`)).GetStorageLensConfigurationTaggingResult?.Tags?.Tag).map((t) => ({ key: t.Key, value: t.Value }));
}
export function putLensConfig(c) {
  const prefix = c.prefixEnabled
    ? `<PrefixLevel><StorageMetrics><IsEnabled>true</IsEnabled><SelectionCriteria><Delimiter>${esc(c.delimiter || "/")}</Delimiter><MaxDepth>${Number(c.maxDepth) || 10}</MaxDepth><MinStorageBytesPercentage>${Number(c.minPct) || 1}</MinStorageBytesPercentage></SelectionCriteria></StorageMetrics></PrefixLevel>` : "";
  const grp = c.groups?.length
    ? `<StorageLensGroupLevel><SelectionCriteria><Include>${c.groups.map((g) => `<Arn>${esc(groupArn(g))}</Arn>`).join("")}</Include></SelectionCriteria></StorageLensGroupLevel>` : "";
  const inc = c.include?.length ? `<Include><Buckets>${c.include.map((b) => `<Arn>arn:aws:s3:::${esc(b)}</Arn>`).join("")}</Buckets></Include>` : "";
  const exc = !c.include?.length && c.exclude?.length ? `<Exclude><Buckets>${c.exclude.map((b) => `<Arn>arn:aws:s3:::${esc(b)}</Arn>`).join("")}</Buckets></Exclude>` : "";
  const body = `<?xml version="1.0" encoding="UTF-8"?><PutStorageLensConfigurationRequest ${CTL_NS}><StorageLensConfiguration><Id>${esc(c.id)}</Id>`
    + `<AccountLevel><ActivityMetrics><IsEnabled>false</IsEnabled></ActivityMetrics><BucketLevel><ActivityMetrics><IsEnabled>false</IsEnabled></ActivityMetrics>${prefix}</BucketLevel>${grp}</AccountLevel>`
    + `${inc}${exc}<IsEnabled>${!!c.enabled}</IsEnabled></StorageLensConfiguration>`
    + (c.tags?.length ? `<Tags>${c.tags.map((t) => `<Tag><Key>${esc(t.key)}</Key><Value>${esc(t.value)}</Value></Tag>`).join("")}</Tags>` : "")
    + "</PutStorageLensConfigurationRequest>";
  return ACCT("PUT", `storagelens/${encodeURIComponent(c.id)}`, { body });
}
export const deleteLensConfig = (id) => ACCT("DELETE", `storagelens/${encodeURIComponent(id)}`);

// Storage Lens groups. A filter is {op: "single"|"And"|"Or", prefixes[], suffixes[], tags[{key,value}], ageGt, ageLt, sizeGt, sizeLt}.
export function filterXml(f) {
  const parts = [];
  if (f.prefixes?.length) parts.push(`<MatchAnyPrefix>${f.prefixes.map((p) => `<Prefix>${esc(p)}</Prefix>`).join("")}</MatchAnyPrefix>`);
  if (f.suffixes?.length) parts.push(`<MatchAnySuffix>${f.suffixes.map((p) => `<Suffix>${esc(p)}</Suffix>`).join("")}</MatchAnySuffix>`);
  if (f.tags?.length) parts.push(`<MatchAnyTag>${f.tags.map((t) => `<Tag><Key>${esc(t.key)}</Key><Value>${esc(t.value)}</Value></Tag>`).join("")}</MatchAnyTag>`);
  if (f.ageGt !== "" && f.ageGt != null || f.ageLt !== "" && f.ageLt != null) {
    parts.push(`<MatchObjectAge>${f.ageGt !== "" && f.ageGt != null ? `<DaysGreaterThan>${Number(f.ageGt)}</DaysGreaterThan>` : ""}${f.ageLt !== "" && f.ageLt != null ? `<DaysLessThan>${Number(f.ageLt)}</DaysLessThan>` : ""}</MatchObjectAge>`);
  }
  if (f.sizeGt !== "" && f.sizeGt != null || f.sizeLt !== "" && f.sizeLt != null) {
    parts.push(`<MatchObjectSize>${f.sizeGt !== "" && f.sizeGt != null ? `<BytesGreaterThan>${Number(f.sizeGt)}</BytesGreaterThan>` : ""}${f.sizeLt !== "" && f.sizeLt != null ? `<BytesLessThan>${Number(f.sizeLt)}</BytesLessThan>` : ""}</MatchObjectSize>`);
  }
  if (parts.length > 1 && f.op === "Or") return `<Or>${parts.join("")}</Or>`;
  if (parts.length > 1) return `<And>${parts.join("")}</And>`;
  return parts.join("");
}
export function parseFilter(flt) {
  const out = { op: "single", prefixes: [], suffixes: [], tags: [], ageGt: "", ageLt: "", sizeGt: "", sizeLt: "" };
  const src = flt?.And ? (out.op = "And", flt.And) : flt?.Or ? (out.op = "Or", flt.Or) : flt || {};
  out.prefixes = asList(src.MatchAnyPrefix?.Prefix);
  out.suffixes = asList(src.MatchAnySuffix?.Suffix);
  out.tags = asList(src.MatchAnyTag?.Tag).map((t) => ({ key: t.Key, value: t.Value }));
  out.ageGt = src.MatchObjectAge?.DaysGreaterThan ?? ""; out.ageLt = src.MatchObjectAge?.DaysLessThan ?? "";
  out.sizeGt = src.MatchObjectSize?.BytesGreaterThan ?? ""; out.sizeLt = src.MatchObjectSize?.BytesLessThan ?? "";
  return out;
}
export function describeFilter(f) {
  const bits = [];
  if (f.prefixes.length) bits.push(`prefix: ${f.prefixes.join(" | ")}`);
  if (f.suffixes.length) bits.push(`suffix: ${f.suffixes.join(" | ")}`);
  if (f.tags.length) bits.push(`tag: ${f.tags.map((t) => `${t.key}=${t.value}`).join(" | ")}`);
  if (f.ageGt !== "" || f.ageLt !== "") bits.push(`age: ${f.ageGt !== "" ? `> ${f.ageGt}d` : ""} ${f.ageLt !== "" ? `< ${f.ageLt}d` : ""}`.trim());
  if (f.sizeGt !== "" || f.sizeLt !== "") bits.push(`size: ${f.sizeGt !== "" ? `> ${f.sizeGt}B` : ""} ${f.sizeLt !== "" ? `< ${f.sizeLt}B` : ""}`.trim());
  return bits.join(f.op === "Or" ? "  OR  " : "  AND  ");
}
export async function listLensGroups() {
  const r = await ACCT("GET", "storagelensgroup");
  return asList(r.ListStorageLensGroupsResult?.StorageLensGroup).map((g) => ({ name: g.Name, arn: g.StorageLensGroupArn, region: g.HomeRegion }));
}
export async function getLensGroup(name) {
  const g = (await ACCT("GET", `storagelensgroup/${encodeURIComponent(name)}`)).StorageLensGroup || {};
  return { name: g.Name, arn: g.StorageLensGroupArn, filter: parseFilter(g.Filter) };
}
export const createLensGroup = (name, filter, tags = []) => ACCT("POST", "storagelensgroup", {
  body: `<?xml version="1.0" encoding="UTF-8"?><CreateStorageLensGroupRequest ${CTL_NS}><StorageLensGroup><Name>${esc(name)}</Name><Filter>${filterXml(filter)}</Filter></StorageLensGroup>`
    + (tags.length ? `<Tags>${tags.map((t) => `<Tag><Key>${esc(t.key)}</Key><Value>${esc(t.value)}</Value></Tag>`).join("")}</Tags>` : "") + "</CreateStorageLensGroupRequest>",
});
export const updateLensGroup = (name, filter) => ACCT("PUT", `storagelensgroup/${encodeURIComponent(name)}`, {
  body: `<?xml version="1.0" encoding="UTF-8"?><UpdateStorageLensGroupRequest ${CTL_NS}><StorageLensGroup><Name>${esc(name)}</Name><Filter>${filterXml(filter)}</Filter></StorageLensGroup></UpdateStorageLensGroupRequest>`,
});
export const deleteLensGroup = (name) => ACCT("DELETE", `storagelensgroup/${encodeURIComponent(name)}`);
