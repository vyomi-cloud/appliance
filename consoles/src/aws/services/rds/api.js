/* RDS over the native wire: the control plane speaks the AWS Query protocol
 * (form-encoded Action=...&..., XML responses) via `awsQuery`; the data plane
 * (Query editor SQL execution) speaks the RDS Data API — a REST-JSON surface
 * reached directly over `/_wire/Execute` (no SigV4 routing needed: the path
 * alone identifies it to the router). */
import { awsQuery, awsJson, asList, WIRE_BASE } from "../../../common/wire.js";

const ACCOUNT_ID = "123456789012";

async function call(action, params = {}) {
  const r = await awsQuery("rds", action, params);
  return r[`${action}Response`]?.[`${action}Result`] ?? {};
}

// ── AWS Query-protocol list flattening ──────────────────────────────────────
const scalarMembers = (prefix, items) =>
  Object.fromEntries((items || []).map((v, i) => [`${prefix}.member.${i + 1}`, v]));

const structMembers = (prefix, items, fields) => {
  const out = {};
  (items || []).forEach((it, i) => fields.forEach((f) => {
    if (it[f] !== undefined) out[`${prefix}.member.${i + 1}.${f}`] = it[f];
  }));
  return out;
};

const tagMembers = (tags) => structMembers("Tags", tags, ["Key", "Value"]);

export const instanceArn = (id) => `arn:aws:rds:us-east-1:${ACCOUNT_ID}:db:${id}`;
export const snapshotArn = (id) => `arn:aws:rds:us-east-1:${ACCOUNT_ID}:snapshot:${id}`;
export const subnetGroupArn = (name) => `arn:aws:rds:us-east-1:${ACCOUNT_ID}:subgrp:${name}`;
export const parameterGroupArn = (name) => `arn:aws:rds:us-east-1:${ACCOUNT_ID}:pg:${name}`;
export const proxyArn = (name) => `arn:aws:rds:us-east-1:${ACCOUNT_ID}:db-proxy:${name}`;
export const optionGroupArn = (name) => `arn:aws:rds:us-east-1:${ACCOUNT_ID}:og:${name}`;

// ── DB instances ─────────────────────────────────────────────────────────────
export async function createDBInstance(input, tags) {
  const r = await call("CreateDBInstance", { ...input, ...tagMembers(tags) });
  return r.DBInstance;
}
export async function describeDBInstances(id) {
  const r = await call("DescribeDBInstances", id ? { DBInstanceIdentifier: id } : {});
  return asList(r.DBInstances?.DBInstance);
}
export async function describeDBInstance(id) {
  return (await describeDBInstances(id))[0];
}
export async function modifyDBInstance(id, fields) {
  const r = await call("ModifyDBInstance", { DBInstanceIdentifier: id, ...fields });
  return r.DBInstance;
}
export async function deleteDBInstance(id, { skipFinalSnapshot = true, finalSnapshotId } = {}) {
  const r = await call("DeleteDBInstance", {
    DBInstanceIdentifier: id, SkipFinalSnapshot: skipFinalSnapshot,
    ...(finalSnapshotId ? { FinalDBSnapshotIdentifier: finalSnapshotId } : {}),
  });
  return r.DBInstance;
}
export const startDBInstance = (id) => call("StartDBInstance", { DBInstanceIdentifier: id });
export const stopDBInstance = (id) => call("StopDBInstance", { DBInstanceIdentifier: id });
export const rebootDBInstance = (id) => call("RebootDBInstance", { DBInstanceIdentifier: id });
export const failoverDBInstance = (id) => call("RebootDBInstance", { DBInstanceIdentifier: id, ForceFailover: true });

// ── Read replicas ────────────────────────────────────────────────────────────
export async function createDBInstanceReadReplica(newId, sourceId, fields = {}) {
  const r = await call("CreateDBInstanceReadReplica", {
    DBInstanceIdentifier: newId, SourceDBInstanceIdentifier: sourceId, ...fields,
  });
  return r.DBInstance;
}
export async function promoteReadReplica(id) {
  const r = await call("PromoteReadReplica", { DBInstanceIdentifier: id });
  return r.DBInstance;
}

// ── DB log files (rds.logs — a real error log derived from genuine failed
// statements, never fabricated) ─────────────────────────────────────────────
export async function describeDBLogFiles(dbInstanceId) {
  const r = await call("DescribeDBLogFiles", { DBInstanceIdentifier: dbInstanceId });
  return asList(r.DescribeDBLogFiles?.DescribeDBLogFilesDetails);
}
export async function downloadDBLogFilePortion(dbInstanceId, logFileName, marker) {
  const r = await call("DownloadDBLogFilePortion", {
    DBInstanceIdentifier: dbInstanceId, LogFileName: logFileName, ...(marker ? { Marker: marker } : {}),
  });
  return { data: r.LogFileData || "", marker: r.Marker, pending: r.AdditionalDataPending === "true" };
}

// ── Snapshots ────────────────────────────────────────────────────────────────
export async function createDBSnapshot(dbInstanceId, snapshotId, tags) {
  const r = await call("CreateDBSnapshot", {
    DBInstanceIdentifier: dbInstanceId, DBSnapshotIdentifier: snapshotId, ...tagMembers(tags),
  });
  return r.DBSnapshot;
}
export async function describeDBSnapshots(dbInstanceId) {
  const r = await call("DescribeDBSnapshots", dbInstanceId ? { DBInstanceIdentifier: dbInstanceId } : {});
  return asList(r.DBSnapshots?.DBSnapshot);
}
export const deleteDBSnapshot = (snapshotId) => call("DeleteDBSnapshot", { DBSnapshotIdentifier: snapshotId });
export async function restoreDBInstanceFromDBSnapshot(newId, snapshotId, fields = {}) {
  const r = await call("RestoreDBInstanceFromDBSnapshot", {
    DBInstanceIdentifier: newId, DBSnapshotIdentifier: snapshotId, ...fields,
  });
  return r.DBInstance;
}

// ── DB subnet groups ─────────────────────────────────────────────────────────
export async function createDBSubnetGroup(name, description, vpcId, subnetIds) {
  const r = await call("CreateDBSubnetGroup", {
    DBSubnetGroupName: name, DBSubnetGroupDescription: description,
    ...(vpcId ? { VpcId: vpcId } : {}), ...scalarMembers("SubnetIds", subnetIds),
  });
  return r.DBSubnetGroup;
}
export async function describeDBSubnetGroups(name) {
  const r = await call("DescribeDBSubnetGroups", name ? { DBSubnetGroupName: name } : {});
  return asList(r.DBSubnetGroups?.DBSubnetGroup);
}
export const deleteDBSubnetGroup = (name) => call("DeleteDBSubnetGroup", { DBSubnetGroupName: name });

// ── DB parameter groups ──────────────────────────────────────────────────────
export async function createDBParameterGroup(name, family, description, type) {
  const r = await call("CreateDBParameterGroup", {
    DBParameterGroupName: name, DBParameterGroupFamily: family,
    Description: description, Type: type,
  });
  return r.DBParameterGroup;
}
export async function describeDBParameterGroups(name) {
  const r = await call("DescribeDBParameterGroups", name ? { DBParameterGroupName: name } : {});
  return asList(r.DBParameterGroups?.DBParameterGroup);
}
export const deleteDBParameterGroup = (name) => call("DeleteDBParameterGroup", { DBParameterGroupName: name });
export async function describeDBParameters(name) {
  const r = await call("DescribeDBParameters", { DBParameterGroupName: name });
  return asList(r.Parameters?.Parameter);
}
export const modifyDBParameterGroup = (name, parameters) => call("ModifyDBParameterGroup", {
  DBParameterGroupName: name,
  ...structMembers("Parameters", parameters, ["ParameterName", "ParameterValue"]),
});

// ── Tags ─────────────────────────────────────────────────────────────────────
export async function listTagsForResource(resourceArn) {
  const r = await call("ListTagsForResource", { ResourceName: resourceArn });
  return asList(r.TagList?.Tag);
}
export const addTagsToResource = (resourceArn, tags) => call("AddTagsToResource", {
  ResourceName: resourceArn, ...tagMembers(tags),
});
export const removeTagsFromResource = (resourceArn, keys) => call("RemoveTagsFromResource", {
  ResourceName: resourceArn, ...scalarMembers("TagKeys", keys),
});

// ── Events ───────────────────────────────────────────────────────────────────
export async function describeEvents(sourceIdentifier) {
  const r = await call("DescribeEvents", sourceIdentifier ? { SourceIdentifier: sourceIdentifier } : {});
  return asList(r.Events?.Event);
}

// ── RDS Proxy ────────────────────────────────────────────────────────────────
export async function createDBProxy(name, engineFamily) {
  const r = await call("CreateDBProxy", { DBProxyName: name, EngineFamily: engineFamily });
  return r.DBProxy;
}
export async function describeDBProxies() {
  const r = await call("DescribeDBProxies", {});
  return asList(r.DBProxies?.DBProxy);
}
export const deleteDBProxy = (name) => call("DeleteDBProxy", { DBProxyName: name });

// ── Option groups ────────────────────────────────────────────────────────────
export async function createOptionGroup(name, description, engineName, majorEngineVersion) {
  const r = await call("CreateOptionGroup", {
    OptionGroupName: name, OptionGroupDescription: description,
    EngineName: engineName, MajorEngineVersion: majorEngineVersion,
  });
  return r.OptionGroup;
}
export async function describeOptionGroups() {
  const r = await call("DescribeOptionGroups", {});
  return asList(r.OptionGroupsList?.OptionGroup);
}
export const deleteOptionGroup = (name) => call("DeleteOptionGroup", { OptionGroupName: name });

// ── Event subscriptions ──────────────────────────────────────────────────────
export async function createEventSubscription(name, snsTopicArn, sourceType) {
  const r = await call("CreateEventSubscription", {
    SubscriptionName: name, SnsTopicArn: snsTopicArn, SourceType: sourceType,
  });
  return r.EventSubscription;
}
export async function describeEventSubscriptions() {
  const r = await call("DescribeEventSubscriptions", {});
  return asList(r.EventSubscriptionsList?.EventSubscription);
}
export const deleteEventSubscription = (name) => call("DeleteEventSubscription", { SubscriptionName: name });

// ── Reserved instances, automated backups, exports, integrations, recommendations ─
export async function describeReservedDBInstances() {
  const r = await call("DescribeReservedDBInstances", {});
  return asList(r.ReservedDBInstances?.ReservedDBInstance);
}
export async function describeDBInstanceAutomatedBackups(dbInstanceId) {
  const r = await call("DescribeDBInstanceAutomatedBackups", dbInstanceId ? { DBInstanceIdentifier: dbInstanceId } : {});
  return asList(r.DBInstanceAutomatedBackups?.DBInstanceAutomatedBackup);
}
export async function describeExportTasks() {
  const r = await call("DescribeExportTasks", {});
  return asList(r.ExportTasks?.ExportTask);
}
export const cancelExportTask = (taskId) => call("CancelExportTask", { ExportTaskIdentifier: taskId });
export async function describeIntegrations() {
  const r = await call("DescribeIntegrations", {});
  return asList(r.Integrations?.Integration);
}
export async function describeDBRecommendations() {
  const r = await call("DescribeDBRecommendations", {});
  return asList(r.DBRecommendations?.DBRecommendation);
}
export async function describeDBEngineVersions() {
  const r = await call("DescribeDBEngineVersions", {});
  return asList(r.DBEngineVersions?.DBEngineVersion);
}
export async function describeCertificates() {
  const r = await call("DescribeCertificates", {});
  return asList(r.Certificates?.Certificate);
}

// ── RDS Data API (Query editor) — REST-JSON, routed by path alone ──────────
export async function executeStatement(dbInstanceIdentifier, sql, { parameters, includeResultMetadata = true } = {}) {
  const res = await fetch(`${WIRE_BASE}/Execute`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      resourceArn: instanceArn(dbInstanceIdentifier),
      secretArn: `arn:aws:secretsmanager:us-east-1:${ACCOUNT_ID}:secret:rds-data-api`,
      sql, parameters, includeResultMetadata,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || `ExecuteStatement failed (${res.status})`);
  return data; // {records, columnMetadata, numberOfRecordsUpdated}
}

// ── CloudWatch (rds.monitoring) — real AWS/RDS datapoints pushed by the core
// off genuine Data API activity (core/rds_core.py's _push_activity_metrics),
// read back over CloudWatch's OWN native wire rather than duplicating its
// engine, same as the EC2 console's Monitoring tab does for StatusCheckFailed. ─
const CW = (op, payload = {}) => awsJson("monitoring", `GraniteServiceVersion20100801.${op}`, payload);
const dbDims = (dbInstanceId) => [{ Name: "DBInstanceIdentifier", Value: dbInstanceId }];
export const RDS_METRICS = ["DatabaseConnections", "ReadIOPS", "WriteIOPS"];

export function getDBInstanceMetric(dbInstanceId, metricName, minutes = 60) {
  const end = new Date(), start = new Date(end - minutes * 60_000);
  return CW("GetMetricStatistics", {
    Namespace: "AWS/RDS", MetricName: metricName, Dimensions: dbDims(dbInstanceId),
    StartTime: start.toISOString(), EndTime: end.toISOString(), Period: 60,
    Statistics: [metricName === "DatabaseConnections" ? "Maximum" : "Sum"],
  }).then((r) => (r.Datapoints || []).sort((a, b) => new Date(a.Timestamp) - new Date(b.Timestamp)));
}

// ── Connected compute resources / Security group rules (rds.replication) —
// real cross-service reads off the EC2/VPC core (core/vpc_core.py), by actual
// security-group membership; never fabricated rows. ─────────────────────────
const EC2 = (action, params = {}) => awsQuery("ec2", action, params).then((r) => r[`${action}Response`] || {});

export async function describeSecurityGroupsById(groupIds) {
  if (!groupIds?.length) return [];
  const params = {};
  groupIds.forEach((id, i) => { params[`GroupId.${i + 1}`] = id; });
  const r = await EC2("DescribeSecurityGroups", params);
  return asList(r.securityGroupInfo?.item).map((sg) => ({
    GroupId: sg.groupId, GroupName: sg.groupName,
    Ingress: asList(sg.ipPermissions?.item).map(permFromXml),
    Egress: asList(sg.ipPermissionsEgress?.item).map(permFromXml),
  }));
}

function permFromXml(x) {
  return {
    IpProtocol: x.ipProtocol,
    FromPort: x.fromPort !== undefined && x.fromPort !== "" ? Number(x.fromPort) : undefined,
    ToPort: x.toPort !== undefined && x.toPort !== "" ? Number(x.toPort) : undefined,
    cidrs: asList(x.ipRanges?.item).map((r) => r.cidrIp),
    groupIds: asList(x.groups?.item).map((g) => g.groupId),
  };
}

export async function describeAllEc2Instances() {
  const r = await EC2("DescribeInstances", {});
  return asList(r.reservationSet?.item).flatMap((res) => asList(res.instancesSet?.item)).map((inst) => ({
    InstanceId: inst.instanceId, InstanceType: inst.instanceType,
    GroupIds: asList(inst.groupSet?.item).map((g) => g.groupId),
  }));
}

export async function describeConnectedComputeResources(groupIds) {
  if (!groupIds?.length) return [];
  const rows = await describeAllEc2Instances();
  return rows
    .filter((row) => row.GroupIds.some((g) => groupIds.includes(g)))
    .map((row) => ({ ...row, ComputeSecurityGroupId: row.GroupIds.find((g) => groupIds.includes(g)) }));
}

export const setUpEc2Connection = (dbSecurityGroupId, ec2SecurityGroupId, port) => EC2("AuthorizeSecurityGroupIngress", {
  GroupId: dbSecurityGroupId, "IpPermissions.1.IpProtocol": "tcp",
  "IpPermissions.1.FromPort": port, "IpPermissions.1.ToPort": port,
  "IpPermissions.1.Groups.1.GroupId": ec2SecurityGroupId,
});
