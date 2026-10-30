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

export const putObject = (bucket, key, body, type) =>
  s3("PUT", `/${bucket}/${enc(key)}`, { body, headers: type ? { "content-type": type } : {} });
export const deleteObject = (bucket, key) => s3("DELETE", `/${bucket}/${enc(key)}`);
export const createFolder = (bucket, key) => s3("PUT", `/${bucket}/${enc(key.endsWith("/") ? key : key + "/")}`, { body: "" });
export const objectUrl = (bucket, key) => `/${bucket}/${enc(key)}`;

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
  return { rules: asList(r.value.LifecycleConfiguration?.Rule).map((x) => ({ id: x.ID, status: x.Status, prefix: x.Filter?.Prefix ?? x.Prefix ?? "" })) };
}

const esc = (s) => String(s).replace(/[<>&'"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" }[c]));
