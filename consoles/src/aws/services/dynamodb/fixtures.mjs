/* UI-conformance fixtures for DynamoDB (native X-Amz-Target JSON). See s3/fixtures.mjs. */
const T = (op) => ({ svc: "dynamodb", target: `DynamoDB_20120810.${op}` });
const table = (name) => ({ TableName: name, AttributeDefinitions: [{ AttributeName: "pk", AttributeType: "S" }], KeySchema: [{ AttributeName: "pk", KeyType: "HASH" }], BillingMode: "PAY_PER_REQUEST" });
export default {
  "ddb-table": async (wire) => { await wire("POST", "/", { ...T("CreateTable"), body: table("uic-table") }).catch(() => {}); return "uic-table"; },
  "live-table": async (wire, uniq) => { await wire("POST", "/", { ...T("CreateTable"), body: table(uniq) }); return uniq; },
  "live-backup": async (wire, uniq) => {
    await wire("POST", "/", { ...T("CreateTable"), body: table("uic-table") }).catch(() => {});
    await wire("POST", "/", { ...T("CreateBackup"), body: { TableName: "uic-table", BackupName: uniq } });
    return uniq;
  },
  "live-item": async (wire, uniq) => {
    await wire("POST", "/", { ...T("CreateTable"), body: table("uic-table") }).catch(() => {});
    await wire("POST", "/", { ...T("PutItem"), body: { TableName: "uic-table", Item: { pk: { S: uniq } } } });
    return uniq;
  },
  "live-export": async (wire, uniq) => {
    await wire("PUT", `/${uniq}`, { svc: "s3" }).catch(() => {});
    await wire("POST", "/", { ...T("CreateTable"), body: table("uic-table") }).catch(() => {});
    await wire("POST", "/", { ...T("PutItem"), body: { TableName: "uic-table", Item: { pk: { S: "x" } } } }).catch(() => {});
    await wire("POST", "/", { ...T("ExportTableToPointInTime"), body: { TableName: "uic-table", S3Bucket: uniq } });
    return uniq;
  },
  "live-import": async (wire, uniq) => {
    const bucket = `ddb-import-${uniq}`;
    await wire("PUT", `/${bucket}`, { svc: "s3" }).catch(() => {});
    await wire("PUT", `/${bucket}/src/data/1.json`, { svc: "s3", body: JSON.stringify({ Item: { pk: { S: "x" } } }) + "\n" });
    await wire("POST", "/", { ...T("ImportTable"), body: {
      S3BucketSource: { S3Bucket: bucket, S3KeyPrefix: "src/" }, InputFormat: "DYNAMODB_JSON",
      TableCreationParameters: { TableName: uniq, AttributeDefinitions: [{ AttributeName: "pk", AttributeType: "S" }],
        KeySchema: [{ AttributeName: "pk", KeyType: "HASH" }], BillingMode: "PAY_PER_REQUEST" },
    } });
    return uniq;
  },
};
