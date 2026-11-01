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
export const exportTableToPointInTime = (input) => call("ExportTableToPointInTime", input).then((r) => r.ExportDescription);
export const listExports = async (tableArn) => (await call("ListExports", tableArn ? { TableArn: tableArn } : {})).ExportSummaries || [];
export const describeExport = (arn) => call("DescribeExport", { ExportArn: arn }).then((r) => r.ExportDescription);
export const importTable = (input) => call("ImportTable", input).then((r) => r.ImportTableDescription);
export const listImports = async (tableArn) => (await call("ListImports", tableArn ? { TableArn: tableArn } : {})).ImportSummaryList || [];
export const describeImport = (arn) => call("DescribeImport", { ImportArn: arn }).then((r) => r.ImportTableDescription);

// ── DynamoDB Streams ─────────────────────────────────────────────────────
export const listStreams = async (tableName) => (await call("ListStreams", { TableName: tableName })).Streams || [];
export const describeStream = (streamArn) => call("DescribeStream", { StreamArn: streamArn }).then((r) => r.StreamDescription);
export const getShardIterator = (streamArn, shardId, type, sequenceNumber) =>
  call("GetShardIterator", { StreamArn: streamArn, ShardId: shardId, ShardIteratorType: type, ...(sequenceNumber ? { SequenceNumber: sequenceNumber } : {}) })
    .then((r) => r.ShardIterator);
export const getRecords = (shardIterator) => call("GetRecords", { ShardIterator: shardIterator });

// ── Kinesis Data Streams destination ─────────────────────────────────────
export const enableKinesisStreamingDestination = (tableName, streamArn) => call("EnableKinesisStreamingDestination", { TableName: tableName, StreamArn: streamArn });
export const disableKinesisStreamingDestination = (tableName, streamArn) => call("DisableKinesisStreamingDestination", { TableName: tableName, StreamArn: streamArn });
export const describeKinesisStreamingDestination = (tableName) => call("DescribeKinesisStreamingDestination", { TableName: tableName }).then((r) => r.KinesisDataStreamDestinations || []);

// ── Resource-based policy ────────────────────────────────────────────────
export const getResourcePolicy = async (arn) => { try { return await call("GetResourcePolicy", { ResourceArn: arn }); } catch (e) { if (e.code === "PolicyNotFoundException") return null; throw e; } };
export const putResourcePolicy = (arn, policy, expectedRevisionId, confirmRemoveSelfResourceAccess) =>
  call("PutResourcePolicy", { ResourceArn: arn, Policy: policy, ...(expectedRevisionId ? { ExpectedRevisionId: expectedRevisionId } : {}),
    ...(confirmRemoveSelfResourceAccess ? { ConfirmRemoveSelfResourceAccess: true } : {}) });
export const deleteResourcePolicy = (arn, expectedRevisionId) => call("DeleteResourcePolicy", { ResourceArn: arn, ...(expectedRevisionId ? { ExpectedRevisionId: expectedRevisionId } : {}) });

// ── Global tables (UpdateTable ReplicaUpdates; see DescribeTable's Replicas) ──
export const createReplica = (tableName, regionName) => call("UpdateTable", { TableName: tableName, ReplicaUpdates: [{ Create: { RegionName: regionName } }] });
export const deleteReplica = (tableName, regionName) => call("UpdateTable", { TableName: tableName, ReplicaUpdates: [{ Delete: { RegionName: regionName } }] });

// ── CloudWatch metrics/alarms for this table (real AWS/DynamoDB datapoints) ──
// Real DynamoDB's console calls straight into CloudWatch for this tab; Vyomi does the
// same native call rather than duplicating CloudWatch's engine (core/cloudwatch_core.py).
const CW = (op, payload = {}) => awsJson("monitoring", `GraniteServiceVersion20100801.${op}`, payload);
const tableDims = (tableName) => [{ Name: "TableName", Value: tableName }];

export const getTableMetric = (tableName, metricName, { minutes = 60, statistic = "Sum" } = {}) => {
  const end = new Date(), start = new Date(end - minutes * 60_000);
  return CW("GetMetricStatistics", {
    Namespace: "AWS/DynamoDB", MetricName: metricName, Dimensions: tableDims(tableName),
    StartTime: start.toISOString(), EndTime: end.toISOString(), Period: 60, Statistics: [statistic],
  }).then((r) => (r.Datapoints || []).sort((a, b) => new Date(a.Timestamp) - new Date(b.Timestamp)));
};
export const describeTableAlarms = (tableName, metricNames) =>
  Promise.all(metricNames.map((m) => CW("DescribeAlarmsForMetric", { Namespace: "AWS/DynamoDB", MetricName: m, Dimensions: tableDims(tableName) })
    .then((r) => r.MetricAlarms || []))).then((lists) => lists.flat());
export const putTableAlarm = (tableName, { alarmName, metricName, statistic, comparison, threshold, evaluationPeriods, snsArn }) =>
  CW("PutMetricAlarm", {
    AlarmName: alarmName, Namespace: "AWS/DynamoDB", MetricName: metricName, Dimensions: tableDims(tableName),
    Statistic: statistic, Period: 60, EvaluationPeriods: evaluationPeriods, DatapointsToAlarm: evaluationPeriods,
    Threshold: threshold, ComparisonOperator: comparison, AlarmActions: snsArn ? [snsArn] : [],
  });
export const deleteTableAlarms = (names) => CW("DeleteAlarms", { AlarmNames: names });

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
