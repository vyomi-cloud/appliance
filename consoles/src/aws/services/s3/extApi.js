/* S3 sweep S3-4 native-wire calls: Transfer acceleration, S3 Metadata (V2), CloudTrail (JSON 1.1, signing name
 * cloudtrail) and the Vyomi-internal bucket-metadata / bucket-trail / bucket-lens JSON routes. */
import { authHeader, awsJson, s3, WIRE_BASE, WireError } from "../../../common/wire.js";

const NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"';
const xml = (b) => `<?xml version="1.0" encoding="UTF-8"?>${b}`;
const ACCOUNT = "123456789012";

// ── Transfer acceleration ──
export async function getAccelerate(b) {
  const r = await s3("GET", `/${b}`, { query: { accelerate: "" } });
  return { status: r.AccelerateConfiguration?.Status || "" };
}
export const putAccelerate = (b, status) => s3("PUT", `/${b}`, { query: { accelerate: "" }, body: xml(`<AccelerateConfiguration ${NS}><Status>${status}</Status></AccelerateConfiguration>`) });

// ── S3 Metadata ──
export async function getMetadataConfig(b) {
  try {
    const r = (await s3("GET", `/${b}`, { query: { metadataConfiguration: "" } })).GetBucketMetadataConfigurationResult?.MetadataConfigurationResult || {};
    const j = r.JournalTableConfigurationResult || {}, i = r.InventoryTableConfigurationResult || {}, d = r.DestinationResult || {};
    return { configured: true, destination: d, journal: { status: j.TableStatus, name: j.TableName, arn: j.TableArn, expiration: j.RecordExpiration?.Expiration, days: j.RecordExpiration?.Days },
             inventory: { state: i.ConfigurationState, status: i.TableStatus, name: i.TableName, arn: i.TableArn } };
  } catch (e) {
    if (e.status === 404) return { configured: false };
    throw e;
  }
}
export const createMetadataConfig = (b, { expire, days, inventory }) => s3("POST", `/${b}`, {
  query: { metadataConfiguration: "" },
  body: xml(`<MetadataConfiguration ${NS}><JournalTableConfiguration><RecordExpiration><Expiration>${expire ? "ENABLED" : "DISABLED"}</Expiration>${expire ? `<Days>${Number(days)}</Days>` : ""}</RecordExpiration></JournalTableConfiguration>`
    + `<InventoryTableConfiguration><ConfigurationState>${inventory ? "ENABLED" : "DISABLED"}</ConfigurationState></InventoryTableConfiguration></MetadataConfiguration>`),
});
export const deleteMetadataConfig = (b) => s3("DELETE", `/${b}`, { query: { metadataConfiguration: "" } });
export const updateInventoryTable = (b, enabled) => s3("PUT", `/${b}`, { query: { metadataInventoryTable: "" },
  body: xml(`<InventoryTableConfiguration ${NS}><ConfigurationState>${enabled ? "ENABLED" : "DISABLED"}</ConfigurationState></InventoryTableConfiguration>`) });
export const updateJournalTable = (b, { expire, days }) => s3("PUT", `/${b}`, { query: { metadataJournalTable: "" },
  body: xml(`<JournalTableConfiguration ${NS}><RecordExpiration><Expiration>${expire ? "ENABLED" : "DISABLED"}</Expiration>${expire ? `<Days>${Number(days)}</Days>` : ""}</RecordExpiration></JournalTableConfiguration>`) });

// ── CloudTrail ──
const CT = (action, payload) => awsJson("cloudtrail", `com.amazonaws.cloudtrail.v20131101.CloudTrail_20131101.${action}`, payload, { version: "1.1" });
export const createDataTrail = async ({ name, destBucket, bucket, readWrite }) => {
  await CT("CreateTrail", { Name: name, S3BucketName: destBucket });
  await CT("PutEventSelectors", { TrailName: name, EventSelectors: [{ ReadWriteType: readWrite, IncludeManagementEvents: false,
    DataResources: [{ Type: "AWS::S3::Object", Values: [`arn:aws:s3:::${bucket}/`] }] }] });
  await CT("StartLogging", { Name: name });
};
export const startTrail = (name) => CT("StartLogging", { Name: name });
export const stopTrail = (name) => CT("StopLogging", { Name: name });
export const deleteTrail = (name) => CT("DeleteTrail", { Name: name });

// ── Vyomi-internal JSON routes ──
async function vy(path, query) {
  const qs = query ? "?" + new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== "")).toString() : "";
  const res = await fetch(`${WIRE_BASE}/v20180820/_vyomi/${path}${qs}`, { headers: { ...authHeader("s3"), "x-amz-account-id": ACCOUNT } });
  const text = await res.text();
  let data = {}; try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text }; }
  if (!res.ok) throw new WireError(res.status, data.error, data.message, text);
  return data;
}
export const metadataRecords = (b, q) => vy(`bucket-metadata/${encodeURIComponent(b)}`, q);
export const dataEvents = (b, q) => vy(`bucket-trail/${encodeURIComponent(b)}`, q);
export const bucketLens = (b) => vy(`bucket-lens/${encodeURIComponent(b)}`);
