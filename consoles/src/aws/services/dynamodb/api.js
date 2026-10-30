/* DynamoDB over the native JSON wire (X-Amz-Target DynamoDB_20120810.*). */
import { awsJson } from "../../../common/wire.js";

const call = (op, body) => awsJson("dynamodb", `DynamoDB_20120810.${op}`, body, { version: "1.0" });

export async function listTables() {
  const names = [];
  let start;
  do {
    const r = await call("ListTables", start ? { ExclusiveStartTableName: start } : {});
    names.push(...(r.TableNames || []));
    start = r.LastEvaluatedTableName;
  } while (start);
  return names;
}

export const describeTable = async (name) => (await call("DescribeTable", { TableName: name })).Table;
export const createTable = (input) => call("CreateTable", input);
export const deleteTable = (name) => call("DeleteTable", { TableName: name });
export const scan = (name, { limit = 50, start } = {}) => call("Scan", { TableName: name, Limit: limit, ...(start ? { ExclusiveStartKey: start } : {}) });
export const query = (input) => call("Query", input);
export const putItem = (name, item) => call("PutItem", { TableName: name, Item: item });
export const deleteItem = (name, key) => call("DeleteItem", { TableName: name, Key: key });
export const tags = async (arn) => { try { return (await call("ListTagsOfResource", { ResourceArn: arn })).Tags || []; } catch (e) { if (e.status === 501 || e.code === "UnknownOperationException") return null; throw e; } };
export const describeTtl = async (name) => { try { return (await call("DescribeTimeToLive", { TableName: name })).TimeToLiveDescription; } catch (e) { if (e.status === 501 || e.code === "UnknownOperationException") return null; throw e; } };
export const describeBackups = async (name) => { try { return (await call("DescribeContinuousBackups", { TableName: name })).ContinuousBackupsDescription; } catch (e) { if (e.status === 501 || e.code === "UnknownOperationException") return null; throw e; } };
export const updateTable = (input) => call("UpdateTable", input);
export const updateTtl = (name, spec) => call("UpdateTimeToLive", { TableName: name, TimeToLiveSpecification: spec });
export const updateContinuousBackups = (name, enabled) => call("UpdateContinuousBackups", { TableName: name, PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: enabled } });
export const createBackup = (tableName, backupName) => call("CreateBackup", { TableName: tableName, BackupName: backupName });
export const listBackups = async (tableName) => (await call("ListBackups", tableName ? { TableName: tableName } : {})).BackupSummaries || [];
export const describeBackup = (arn) => call("DescribeBackup", { BackupArn: arn }).then((r) => r.BackupDescription);
export const deleteBackup = (arn) => call("DeleteBackup", { BackupArn: arn });
export const restoreTableFromBackup = (arn, targetTableName) => call("RestoreTableFromBackup", { BackupArn: arn, TargetTableName: targetTableName });
export const executeStatement = (statement, parameters) => call("ExecuteStatement", { Statement: statement, ...(parameters ? { Parameters: parameters } : {}) });

/** DynamoDB attribute-value JSON → plain JS, and back. */
export function unmarshal(av) {
  if (!av || typeof av !== "object") return av;
  const [t, v] = Object.entries(av)[0] || [];
  switch (t) {
    case "S": return v;
    case "N": return Number(v);
    case "BOOL": return v;
    case "NULL": return null;
    case "SS": case "BS": return v;
    case "NS": return v.map(Number);
    case "L": return v.map(unmarshal);
    case "M": return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, unmarshal(x)]));
    case "B": return `<binary ${v.length} b64>`;
    default: return av;
  }
}
export const unmarshalItem = (item) => Object.fromEntries(Object.entries(item || {}).map(([k, v]) => [k, unmarshal(v)]));

export function marshal(v) {
  if (v === null) return { NULL: true };
  if (typeof v === "string") return { S: v };
  if (typeof v === "number") return { N: String(v) };
  if (typeof v === "boolean") return { BOOL: v };
  if (Array.isArray(v)) return { L: v.map(marshal) };
  if (typeof v === "object") return { M: Object.fromEntries(Object.entries(v).map(([k, x]) => [k, marshal(x)])) };
  return { S: String(v) };
}
export const marshalItem = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, marshal(v)]));
export const avType = (av) => Object.keys(av || {})[0] || "-";
