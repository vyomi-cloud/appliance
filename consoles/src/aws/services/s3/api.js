/* S3 over the native REST wire (path-style). Every call here is a real S3 API operation. */
import { asList, getRegion, s3, WireError } from "../../../common/wire.js";

const enc = (k) => k.split("/").map(encodeURIComponent).join("/");
const xml = (body) => `<?xml version="1.0" encoding="UTF-8"?>${body}`;
const NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"';

export async function listBuckets() {
  const r = await s3("GET", "/");
  return asList(r.ListAllMyBucketsResult?.Buckets?.Bucket).map((b) => ({ name: b.Name, created: b.CreationDate }));
}

export async function bucketRegion(name) {
  try {
    const r = await s3("GET", `/${name}`, { query: { location: "" } });
    const c = r.LocationConstraint;
    return (typeof c === "string" ? c : "") || "us-east-1";
  } catch { return null; }
}

export async function createBucket(name, { objectLock = false } = {}) {
  const region = getRegion();
  const body = region === "us-east-1" ? undefined
    : xml(`<CreateBucketConfiguration ${NS}><LocationConstraint>${region}</LocationConstraint></CreateBucketConfiguration>`);
  return s3("PUT", `/${name}`, { body, headers: objectLock ? { "x-amz-bucket-object-lock-enabled": "true" } : {} });
}

export const deleteBucket = (name) => s3("DELETE", `/${name}`);

/** Every key in the bucket, recursively (no delimiter), across pages — used to empty a bucket. */
export async function listAllObjectKeys(bucket) {
  const keys = [];
  let token;
  do {
    const r = await s3("GET", `/${bucket}`, { query: { "list-type": "2", "continuation-token": token } });
    const res = r.ListBucketResult || {};
    keys.push(...asList(res.Contents).map((o) => o.Key));
    token = res.IsTruncated === "true" ? res.NextContinuationToken : null;
  } while (token);
  return keys;
}

export async function listObjects(bucket, prefix = "", token) {
  const r = await s3("GET", `/${bucket}`, { query: { "list-type": "2", prefix, delimiter: "/", "continuation-token": token } });
  const res = r.ListBucketResult || {};
  return {
    folders: asList(res.CommonPrefixes).map((p) => ({ key: p.Prefix, name: p.Prefix.slice(prefix.length), folder: true })),
    objects: asList(res.Contents).filter((o) => o.Key !== prefix).map((o) => ({
      key: o.Key, name: o.Key.slice(prefix.length), size: Number(o.Size || 0), modified: o.LastModified, etag: o.ETag, storageClass: o.StorageClass || "STANDARD",
    })),
    next: res.IsTruncated === "true" ? res.NextContinuationToken : null,
  };
}

export const putObject = (bucket, key, body, type, extraHeaders) =>
  s3("PUT", `/${bucket}/${enc(key)}`, { body, headers: { ...(type ? { "content-type": type } : {}), ...extraHeaders } });
export const deleteObject = (bucket, key, versionId) => s3("DELETE", `/${bucket}/${enc(key)}`, { query: versionId ? { versionId } : undefined });
export const createFolder = (bucket, key) => s3("PUT", `/${bucket}/${enc(key.endsWith("/") ? key : key + "/")}`, { body: "" });
export const objectUrl = (bucket, key) => `/${bucket}/${enc(key)}`;

/** HeadObject — real per-object metadata (size, type, etag, storage class, version, custom x-amz-meta-*). */
export async function headObject(bucket, key) {
  const r = await s3("HEAD", `/${bucket}/${enc(key)}`, { raw: true });
  const meta = {};
  for (const [k, v] of r.headers.entries()) if (k.startsWith("x-amz-meta-")) meta[k.slice(11)] = v;
  return {
    size: Number(r.headers.get("content-length") || 0),
    contentType: r.headers.get("content-type") || "application/octet-stream",
    etag: r.headers.get("etag") || "",
    lastModified: r.headers.get("last-modified") || "",
    storageClass: r.headers.get("x-amz-storage-class") || "STANDARD",
    versionId: r.headers.get("x-amz-version-id") || "null",
    encryption: r.headers.get("x-amz-server-side-encryption") || null,
    kmsKeyId: r.headers.get("x-amz-server-side-encryption-aws-kms-key-id") || null,
    metadata: meta,
  };
}

/** ListObjectVersions scoped to a single key — every version this key has ever had. */
export async function listObjectVersions(bucket, key) {
  const r = await s3("GET", `/${bucket}`, { query: { versions: "", prefix: key } });
  const res = r.ListVersionsResult || {};
  const toRow = (v, deleteMarker) => ({
    versionId: v.VersionId, deleteMarker, isLatest: v.IsLatest === "true",
    modified: v.LastModified, size: Number(v.Size || 0), etag: v.ETag, storageClass: v.StorageClass || "STANDARD",
  });
  return [
    ...asList(res.Version).map((v) => toRow(v, false)),
    ...asList(res.DeleteMarker).map((v) => toRow(v, true)),
  ].sort((a, b) => (a.modified < b.modified ? 1 : -1));
}

/** Sub-resource GET that may legitimately be absent (404 "no config") or unsupported (501). */
async function sub(bucket, q) {
  try { return { value: await s3("GET", `/${bucket}`, { query: { [q]: "" } }) }; }
  catch (e) {
    if (e instanceof WireError && (e.status === 501 || e.code === "NotImplemented")) return { unsupported: true };
    if (e instanceof WireError && e.status === 404) return { absent: true, code: e.code };
    return { error: e };
  }
}

export async function getVersioning(b) {
  const r = await sub(b, "versioning");
  if (!r.value) return r;
  const s = r.value.VersioningConfiguration?.Status;
  return { status: typeof s === "string" && s ? s : "Disabled" };
}
export const putVersioning = (b, enabled) =>
  s3("PUT", `/${b}`, { query: { versioning: "" }, body: xml(`<VersioningConfiguration ${NS}><Status>${enabled ? "Enabled" : "Suspended"}</Status></VersioningConfiguration>`) });

export async function getTags(b) {
  const r = await sub(b, "tagging");
  if (r.absent) return { tags: [] };
  if (!r.value) return r;
  return { tags: asList(r.value.Tagging?.TagSet?.Tag).map((t) => ({ key: t.Key, value: t.Value || "" })) };
}
export const putTags = (b, tags) => tags.length
  ? s3("PUT", `/${b}`, { query: { tagging: "" }, body: xml(`<Tagging ${NS}><TagSet>${tags.map((t) => `<Tag><Key>${esc(t.key)}</Key><Value>${esc(t.value)}</Value></Tag>`).join("")}</TagSet></Tagging>`) })
  : s3("DELETE", `/${b}`, { query: { tagging: "" } });

export async function getEncryption(b) {
  const r = await sub(b, "encryption");
  if (!r.value) return r;
  const rule = asList(r.value.ServerSideEncryptionConfiguration?.Rule)[0] || {};
  const d = rule.ApplyServerSideEncryptionByDefault || {};
  return { algorithm: d.SSEAlgorithm || "AES256", kmsKey: d.KMSMasterKeyID, bucketKey: rule.BucketKeyEnabled === "true" };
}
export const putEncryption = (b, algorithm, kmsKey, bucketKey) => s3("PUT", `/${b}`, {
  query: { encryption: "" },
  body: xml(`<ServerSideEncryptionConfiguration ${NS}><Rule><ApplyServerSideEncryptionByDefault><SSEAlgorithm>${algorithm}</SSEAlgorithm>${kmsKey ? `<KMSMasterKeyID>${esc(kmsKey)}</KMSMasterKeyID>` : ""}</ApplyServerSideEncryptionByDefault>${bucketKey ? "<BucketKeyEnabled>true</BucketKeyEnabled>" : ""}</Rule></ServerSideEncryptionConfiguration>`),
});

export async function getPublicAccessBlock(b) {
  const r = await sub(b, "publicAccessBlock");
  if (r.absent) return { config: null };
  if (!r.value) return r;
  const c = r.value.PublicAccessBlockConfiguration || {};
  return { config: Object.fromEntries(["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"].map((k) => [k, c[k] === "true"])) };
}
export const putPublicAccessBlock = (b, c) => s3("PUT", `/${b}`, {
  query: { publicAccessBlock: "" },
  body: xml(`<PublicAccessBlockConfiguration ${NS}>${Object.entries(c).map(([k, v]) => `<${k}>${v}</${k}>`).join("")}</PublicAccessBlockConfiguration>`),
});

export async function getPolicy(b) {
  try {
    const r = await s3("GET", `/${b}`, { query: { policy: "" }, raw: true });
    return { policy: r.text };
  } catch (e) {
    if (e.status === 404) return { policy: null };
    if (e.status === 501) return { unsupported: true };
    return { error: e };
  }
}

export async function getLifecycle(b) {
  const r = await sub(b, "lifecycle");
  if (r.absent) return { rules: [] };
  if (!r.value) return r;
  return {
    rules: asList(r.value.LifecycleConfiguration?.Rule).map((x) => ({
      id: x.ID, status: x.Status, prefix: x.Filter?.Prefix ?? x.Prefix ?? "",
      expirationDays: x.Expiration?.Days ? Number(x.Expiration.Days) : null,
      expirationDate: x.Expiration?.Date || null,
    })),
  };
}
const lifecycleRuleXml = (r) => `<Rule><ID>${esc(r.id)}</ID><Status>${r.status}</Status><Filter><Prefix>${esc(r.prefix || "")}</Prefix></Filter>${
  r.expirationDate ? `<Expiration><Date>${esc(r.expirationDate)}</Date></Expiration>`
    : r.expirationDays ? `<Expiration><Days>${r.expirationDays}</Days></Expiration>` : ""}</Rule>`;
export const putLifecycleRules = (b, rules) => rules.length
  ? s3("PUT", `/${b}`, { query: { lifecycle: "" }, body: xml(`<LifecycleConfiguration ${NS}>${rules.map(lifecycleRuleXml).join("")}</LifecycleConfiguration>`) })
  : s3("DELETE", `/${b}`, { query: { lifecycle: "" } });

const esc = (s) => String(s).replace(/[<>&'"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[c]));

// ── Permissions sub-resources (W1: every one round-trips through the native API) ──
export const putPolicy = (b, json) => s3("PUT", `/${b}`, { query: { policy: "" }, body: json, headers: { "content-type": "application/json" } });
export const deletePolicy = (b) => s3("DELETE", `/${b}`, { query: { policy: "" } });

export async function getOwnership(b) {
  const r = await sub(b, "ownershipControls");
  if (r.absent) return { ownership: null };
  if (!r.value) return r;
  return { ownership: asList(r.value.OwnershipControls?.Rule)[0]?.ObjectOwnership || null };
}
export const putOwnership = (b, ownership) => s3("PUT", `/${b}`, {
  query: { ownershipControls: "" },
  body: xml(`<OwnershipControls ${NS}><Rule><ObjectOwnership>${ownership}</ObjectOwnership></Rule></OwnershipControls>`),
});

export async function getAcl(b) {
  const r = await sub(b, "acl");
  if (!r.value) return r;
  const p = r.value.AccessControlPolicy || {};
  return {
    owner: p.Owner?.DisplayName || p.Owner?.ID,
    grants: asList(p.AccessControlList?.Grant).map((g) => ({
      grantee: g.Grantee?.DisplayName || g.Grantee?.URI || g.Grantee?.ID || "-",
      type: g.Grantee?.URI ? "Group" : "Canonical user",
      permission: g.Permission,
    })),
  };
}
export const putAcl = (b, canned) => s3("PUT", `/${b}`, { query: { acl: "" }, headers: { "x-amz-acl": canned } });

export async function getObjectAcl(b, key) {
  try {
    const r = await s3("GET", `/${b}/${enc(key)}`, { query: { acl: "" } });
    const p = r.AccessControlPolicy || {};
    return {
      owner: p.Owner?.DisplayName || p.Owner?.ID,
      grants: asList(p.AccessControlList?.Grant).map((g) => ({
        grantee: g.Grantee?.DisplayName || g.Grantee?.URI || g.Grantee?.ID || "-",
        type: g.Grantee?.URI ? "Group" : "Canonical user",
        permission: g.Permission,
      })),
    };
  } catch (e) { return { error: e }; }
}
export const putObjectAcl = (b, key, canned) => s3("PUT", `/${b}/${enc(key)}`, { query: { acl: "" }, headers: { "x-amz-acl": canned } });

export async function getObjectLock(b) {
  try {
    const r = await s3("GET", `/${b}`, { query: { "object-lock": "" } });
    const rule = r.ObjectLockConfiguration?.Rule?.DefaultRetention;
    return {
      enabled: r.ObjectLockConfiguration?.ObjectLockEnabled === "Enabled",
      defaultRetention: rule ? { mode: rule.Mode, days: rule.Days, years: rule.Years } : null,
    };
  } catch (e) {
    if (e.status === 404) return { enabled: false };
    return { error: e };
  }
}

export const putObjectLockDefaultRetention = (b, mode, period, unit) => s3("PUT", `/${b}`, {
  query: { "object-lock": "" },
  body: xml(`<ObjectLockConfiguration ${NS}><ObjectLockEnabled>Enabled</ObjectLockEnabled><Rule><DefaultRetention>`
    + `<Mode>${mode}</Mode><${unit}>${period}</${unit}></DefaultRetention></Rule></ObjectLockConfiguration>`),
});

export const clearObjectLockDefaultRetention = (b) => s3("PUT", `/${b}`, {
  query: { "object-lock": "" },
  body: xml(`<ObjectLockConfiguration ${NS}><ObjectLockEnabled>Enabled</ObjectLockEnabled></ObjectLockConfiguration>`),
});

export async function getLegalHold(b, key) {
  try {
    const r = await s3("GET", `/${b}/${enc(key)}`, { query: { "legal-hold": "" } });
    return { status: r.LegalHold?.Status || "OFF" };
  } catch (e) {
    if (e.status === 501 || e.status === 400) return { unsupported: true };
    return { error: e };
  }
}
export const putLegalHold = (b, key, status) => s3("PUT", `/${b}/${enc(key)}`, { query: { "legal-hold": "" }, body: xml(`<LegalHold ${NS}><Status>${status}</Status></LegalHold>`) });

export async function getRetention(b, key) {
  try {
    const r = await s3("GET", `/${b}/${enc(key)}`, { query: { retention: "" } });
    return { mode: r.Retention?.Mode || null, retainUntil: r.Retention?.RetainUntilDate || null };
  } catch (e) {
    if (e.status === 404) return { mode: null };
    if (e.status === 501 || e.status === 400) return { unsupported: true };
    return { error: e };
  }
}
export const putRetention = (b, key, mode, retainUntil, bypass) => s3("PUT", `/${b}/${enc(key)}`, {
  query: { retention: "" },
  body: xml(`<Retention ${NS}><Mode>${mode}</Mode><RetainUntilDate>${retainUntil}</RetainUntilDate></Retention>`),
  headers: bypass ? { "x-amz-bypass-governance-retention": "true" } : {},
});

export async function getWebsite(b) {
  const r = await sub(b, "website");
  if (r.absent) return { config: null };
  if (!r.value) return r;
  const w = r.value.WebsiteConfiguration || {};
  return { config: { indexDocument: w.IndexDocument?.Suffix || "", errorDocument: w.ErrorDocument?.Key || "" } };
}
export const putWebsite = (b, indexDocument, errorDocument) => s3("PUT", `/${b}`, {
  query: { website: "" },
  body: xml(`<WebsiteConfiguration ${NS}><IndexDocument><Suffix>${esc(indexDocument)}</Suffix></IndexDocument>${errorDocument ? `<ErrorDocument><Key>${esc(errorDocument)}</Key></ErrorDocument>` : ""}</WebsiteConfiguration>`),
});
export const deleteWebsite = (b) => s3("DELETE", `/${b}`, { query: { website: "" } });

export async function getLogging(b) {
  const r = await s3("GET", `/${b}`, { query: { logging: "" } });
  const le = r.BucketLoggingStatus?.LoggingEnabled;
  return { enabled: !!le, targetBucket: le?.TargetBucket || "", targetPrefix: le?.TargetPrefix || "" };
}
export const putLogging = (b, targetBucket, targetPrefix) => s3("PUT", `/${b}`, {
  query: { logging: "" },
  body: xml(targetBucket
    ? `<BucketLoggingStatus ${NS}><LoggingEnabled><TargetBucket>${esc(targetBucket)}</TargetBucket><TargetPrefix>${esc(targetPrefix || "")}</TargetPrefix></LoggingEnabled></BucketLoggingStatus>`
    : `<BucketLoggingStatus ${NS}/>`),
});

export async function getRequestPayment(b) {
  const r = await s3("GET", `/${b}`, { query: { requestPayment: "" } });
  return { payer: r.RequestPaymentConfiguration?.Payer || "BucketOwner" };
}
export const putRequestPayment = (b, payer) => s3("PUT", `/${b}`, {
  query: { requestPayment: "" },
  body: xml(`<RequestPaymentConfiguration ${NS}><Payer>${payer}</Payer></RequestPaymentConfiguration>`),
});

export async function getIntelligentTiering(b) {
  const r = await s3("GET", `/${b}`, { query: { "intelligent-tiering": "" } });
  return { configs: asList(r.ListBucketIntelligentTieringConfigurationsOutput?.IntelligentTieringConfiguration).map((c) => ({
    id: c.Id, status: c.Status, tierings: asList(c.Tierings?.Tiering).map((t) => ({ accessTier: t.AccessTier, days: Number(t.Days) })),
  })) };
}
export const putIntelligentTiering = (b, id, status, tierings) => s3("PUT", `/${b}`, {
  query: { "intelligent-tiering": "", id },
  body: xml(`<IntelligentTieringConfiguration ${NS}><Id>${esc(id)}</Id><Status>${status}</Status><Tierings>${tierings.map((t) => `<Tiering><AccessTier>${t.accessTier}</AccessTier><Days>${t.days}</Days></Tiering>`).join("")}</Tierings></IntelligentTieringConfiguration>`),
});
export const deleteIntelligentTiering = (b, id) => s3("DELETE", `/${b}`, { query: { "intelligent-tiering": "", id } });

export async function getInventory(b) {
  const r = await s3("GET", `/${b}`, { query: { inventory: "" } });
  return { configs: asList(r.ListInventoryConfigurationsResult?.InventoryConfiguration).map((c) => ({
    id: c.Id, enabled: c.IsEnabled === "true", destination: (c.Destination?.S3BucketDestination?.Bucket || "").split(":::").pop() || "",
    format: c.Destination?.S3BucketDestination?.Format, frequency: c.Schedule?.Frequency, includedVersions: c.IncludedObjectVersions,
  })) };
}
export const putInventory = (b, { id, destinationBucket, format = "CSV", frequency = "Daily", includedVersions = "Current" }) => s3("PUT", `/${b}`, {
  query: { inventory: "", id },
  body: xml(`<InventoryConfiguration ${NS}><Id>${esc(id)}</Id><IsEnabled>true</IsEnabled><IncludedObjectVersions>${includedVersions}</IncludedObjectVersions><Schedule><Frequency>${frequency}</Frequency></Schedule><Destination><S3BucketDestination><Bucket>arn:aws:s3:::${esc(destinationBucket)}</Bucket><Format>${format}</Format></S3BucketDestination></Destination></InventoryConfiguration>`),
});
export const deleteInventory = (b, id) => s3("DELETE", `/${b}`, { query: { inventory: "", id } });

export async function getMetricsConfigs(b) {
  const r = await s3("GET", `/${b}`, { query: { metrics: "" } });
  return { configs: asList(r.ListBucketMetricsConfigurationsResult?.MetricsConfiguration).map((c) => ({ id: c.Id, prefix: c.Filter?.Prefix || "" })) };
}
export const putMetricsConfig = (b, id, prefix) => s3("PUT", `/${b}`, {
  query: { metrics: "", id },
  body: xml(`<MetricsConfiguration ${NS}><Id>${esc(id)}</Id>${prefix ? `<Filter><Prefix>${esc(prefix)}</Prefix></Filter>` : ""}</MetricsConfiguration>`),
});
export const deleteMetricsConfig = (b, id) => s3("DELETE", `/${b}`, { query: { metrics: "", id } });

const REPLICATION_ROLE = "arn:aws:iam::000000000000:role/vyomi-s3-replication";
export async function getReplication(b) {
  const r = await sub(b, "replication");
  if (r.absent) return { rules: [] };
  if (!r.value) return r;
  return { rules: asList(r.value.ReplicationConfiguration?.Rule).map((x) => ({
    id: x.ID, status: x.Status, prefix: x.Filter?.Prefix ?? "", destination: (x.Destination?.Bucket || "").split(":::").pop() || "",
  })) };
}
const replicationRuleXml = (r) => `<Rule><ID>${esc(r.id)}</ID><Status>${r.status}</Status><Filter><Prefix>${esc(r.prefix || "")}</Prefix></Filter><Destination><Bucket>arn:aws:s3:::${esc(r.destination)}</Bucket></Destination></Rule>`;
export const putReplicationRules = (b, rules) => rules.length
  ? s3("PUT", `/${b}`, { query: { replication: "" }, body: xml(`<ReplicationConfiguration ${NS}><Role>${REPLICATION_ROLE}</Role>${rules.map(replicationRuleXml).join("")}</ReplicationConfiguration>`) })
  : s3("DELETE", `/${b}`, { query: { replication: "" } });

export async function getCors(b) {
  const r = await sub(b, "cors");
  if (r.absent) return { rules: null };
  if (!r.value) return r;
  return {
    rules: asList(r.value.CORSConfiguration?.CORSRule).map((x) => ({
      AllowedHeaders: asList(x.AllowedHeader), AllowedMethods: asList(x.AllowedMethod), AllowedOrigins: asList(x.AllowedOrigin),
      ExposeHeaders: asList(x.ExposeHeader), ...(x.MaxAgeSeconds ? { MaxAgeSeconds: Number(x.MaxAgeSeconds) } : {}),
    })),
  };
}
const tagList = (name, xs) => (xs || []).map((v) => `<${name}>${esc(v)}</${name}>`).join("");
export const putCors = (b, rules) => rules.length
  ? s3("PUT", `/${b}`, { query: { cors: "" }, body: xml(`<CORSConfiguration ${NS}>${rules.map((r) => `<CORSRule>${tagList("AllowedHeader", r.AllowedHeaders)}${tagList("AllowedMethod", r.AllowedMethods)}${tagList("AllowedOrigin", r.AllowedOrigins)}${tagList("ExposeHeader", r.ExposeHeaders)}${r.MaxAgeSeconds ? `<MaxAgeSeconds>${r.MaxAgeSeconds}</MaxAgeSeconds>` : ""}</CORSRule>`).join("")}</CORSConfiguration>`) })
  : s3("DELETE", `/${b}`, { query: { cors: "" } });
