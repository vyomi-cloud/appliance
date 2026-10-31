/* EC2 over the native EC2 Query protocol (form-encoded Action=.../XML responses).
 * EC2 and VPC share one AWS service ("ec2" credential scope) and one backend
 * core (core/vpc_core.py) — this file only covers the compute/storage/network
 * resource surface the v4 EC2 console needs. */
import { awsQuery, awsJson, asList } from "../../../common/wire.js";

/** Flatten a JS object/array into the Query wire's dotted-index form:
 * {InstanceId: ["i-1"]} -> {"InstanceId.1": "i-1"}
 * {IpPermissions: [{IpProtocol: "tcp", IpRanges: [{CidrIp: "0.0.0.0/0"}]}]}
 *   -> {"IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0"} */
export function flatten(value, prefix = "", out = {}) {
  if (value === undefined || value === null || value === "") return out;
  if (Array.isArray(value)) value.forEach((v, i) => flatten(v, prefix ? `${prefix}.${i + 1}` : String(i + 1), out));
  else if (typeof value === "object") Object.entries(value).forEach(([k, v]) => flatten(v, prefix ? `${prefix}.${k}` : k, out));
  else out[prefix] = value;
  return out;
}

const call = (action, params = {}) => awsQuery("ec2", action, flatten(params)).then((r) => r[`${action}Response`] || {});

export const tagsFromXml = (x) => Object.fromEntries(asList(x?.item).map((t) => [t.key, t.value || ""]));
export const tagsToArray = (tags) => Object.entries(tags || {}).filter(([k]) => k).map(([Key, Value]) => ({ Key, Value }));
export const tagSpec = (resourceType, tags) => (Object.keys(tags || {}).length ? [{ ResourceType: resourceType, Tag: tagsToArray(tags) }] : undefined);

export const permFromXml = (x) => ({
  IpProtocol: x.ipProtocol, FromPort: x.fromPort !== undefined && x.fromPort !== "" ? Number(x.fromPort) : undefined,
  ToPort: x.toPort !== undefined && x.toPort !== "" ? Number(x.toPort) : undefined,
  cidrs: asList(x.ipRanges?.item).map((r) => r.cidrIp), groupIds: asList(x.groups?.item).map((g) => g.groupId),
  RuleId: x.securityGroupRuleId, Description: x.description,
});

// ── instances ─────────────────────────────────────────────────────────
const instanceFromXml = (x) => ({ ...x, GroupSet: asList(x.groupSet?.item), Tags: tagsFromXml(x.tagSet), BlockDeviceMapping: asList(x.blockDeviceMapping?.item) });

export async function runInstances(input) {
  const r = await call("RunInstances", input);
  return asList(r.instancesSet?.item).map(instanceFromXml);
}
export async function describeInstances(filter = {}) {
  const r = await call("DescribeInstances", filter);
  return asList(r.reservationSet?.item).flatMap((res) => asList(res.instancesSet?.item)).map(instanceFromXml);
}
export const describeInstance = (id) => describeInstances({ InstanceId: [id] }).then((xs) => xs[0]);
export const startInstances = (ids) => call("StartInstances", { InstanceId: ids });
export const stopInstances = (ids, force) => call("StopInstances", { InstanceId: ids, Force: force });
export const rebootInstances = (ids) => call("RebootInstances", { InstanceId: ids });
export const terminateInstances = (ids, force) => call("TerminateInstances", { InstanceId: ids, Force: force });
export const modifyInstanceAttribute = (id, attr) => call("ModifyInstanceAttribute", { InstanceId: id, ...attr });
export const monitorInstances = (ids) => call("MonitorInstances", { InstanceId: ids });
export const unmonitorInstances = (ids) => call("UnmonitorInstances", { InstanceId: ids });
export async function describeInstanceStatus(id) {
  const r = await call("DescribeInstanceStatus", { InstanceId: [id], IncludeAllInstances: true });
  return asList(r.instanceStatusSet?.item)[0];
}

export async function describeInstanceTypes() {
  const r = await call("DescribeInstanceTypes");
  return asList(r.instanceTypeSet?.item).map((x) => ({
    InstanceType: x.instanceType, FreeTierEligible: x.freeTierEligible === "true", BareMetal: x.bareMetal === "true",
    Hypervisor: x.hypervisor, VCpuCount: Number(x.vCpuInfo?.defaultVCpus || 0), MemoryMiB: Number(x.memoryInfo?.sizeInMiB || 0),
    Architectures: asList(x.processorInfo?.supportedArchitectures?.item), NetworkPerformance: x.networkInfo?.networkPerformance,
  }));
}
export async function describeSubnets() {
  const r = await call("DescribeSubnets");
  return asList(r.subnetSet?.item);
}
export async function describeAvailabilityZones() {
  const r = await call("DescribeAvailabilityZones");
  return asList(r.availabilityZoneInfo?.item).map((x) => ({ ZoneName: x.zoneName, ZoneId: x.zoneId, State: x.state, RegionName: x.regionName }));
}

// ── AMIs ──────────────────────────────────────────────────────────────
const imageFromXml = (x) => ({ ...x, Tags: tagsFromXml(x.tagSet), LaunchPermissions: asList(x.launchPermission?.item).map((p) => p.userId), BlockDeviceMapping: asList(x.blockDeviceMapping?.item) });

export const createImage = (input) => call("CreateImage", input).then((r) => r.imageId);
export async function describeImages(filter = {}) {
  const r = await call("DescribeImages", filter);
  return asList(r.imagesSet?.item).map(imageFromXml);
}
export const describeImage = (id) => describeImages({ ImageId: [id] }).then((xs) => xs[0]);
export const deregisterImage = (id) => call("DeregisterImage", { ImageId: id });
export const copyImage = (sourceImageId, name) => call("CopyImage", { SourceImageId: sourceImageId, Name: name }).then((r) => r.imageId);
export const addLaunchPermission = (id, accountId) => call("ModifyImageAttribute", { ImageId: id, LaunchPermission: { Add: [{ UserId: accountId }] } });
export const removeLaunchPermission = (id, accountId) => call("ModifyImageAttribute", { ImageId: id, LaunchPermission: { Remove: [{ UserId: accountId }] } });

// ── EBS volumes & snapshots ─────────────────────────────────────────────
const volumeFromXml = (x) => ({ ...x, Tags: tagsFromXml(x.tagSet), Attachments: asList(x.attachmentSet?.item) });
const snapshotFromXml = (x) => ({ ...x, Tags: tagsFromXml(x.tagSet) });

export const createVolume = (input) => call("CreateVolume", input).then(volumeFromXml);
export async function describeVolumes(filter = {}) {
  const r = await call("DescribeVolumes", filter);
  return asList(r.volumeSet?.item).map(volumeFromXml);
}
export const describeVolume = (id) => describeVolumes({ VolumeId: [id] }).then((xs) => xs[0]);
export const attachVolume = (volumeId, instanceId, device) => call("AttachVolume", { VolumeId: volumeId, InstanceId: instanceId, Device: device });
export const detachVolume = (volumeId, instanceId, force) => call("DetachVolume", { VolumeId: volumeId, InstanceId: instanceId, Force: force });
export const deleteVolume = (id) => call("DeleteVolume", { VolumeId: id });
export const modifyVolume = (id, input) => call("ModifyVolume", { VolumeId: id, ...input });

export const createSnapshot = (volumeId, description, tags) => call("CreateSnapshot", { VolumeId: volumeId, Description: description, TagSpecification: tagSpec("snapshot", tags) }).then(snapshotFromXml);
export async function describeSnapshots(filter = {}) {
  const r = await call("DescribeSnapshots", filter);
  return asList(r.snapshotSet?.item).map(snapshotFromXml);
}
export const deleteSnapshot = (id) => call("DeleteSnapshot", { SnapshotId: id });
export const copySnapshot = (sourceSnapshotId, description) => call("CopySnapshot", { SourceSnapshotId: sourceSnapshotId, Description: description }).then((r) => r.snapshotId);

// ── key pairs ─────────────────────────────────────────────────────────
const keyPairFromXml = (x) => ({ ...x, Tags: tagsFromXml(x.tagSet) });
export const createKeyPair = (name, keyType) => call("CreateKeyPair", { KeyName: name, KeyType: keyType });
export const importKeyPair = (name, publicKeyMaterialB64) => call("ImportKeyPair", { KeyName: name, PublicKeyMaterial: publicKeyMaterialB64 });
export async function describeKeyPairs() {
  const r = await call("DescribeKeyPairs");
  return asList(r.keySet?.item).map(keyPairFromXml);
}
export const deleteKeyPair = (name) => call("DeleteKeyPair", { KeyName: name });

// ── elastic IPs ───────────────────────────────────────────────────────
const addressFromXml = (x) => ({ ...x, Tags: tagsFromXml(x.tagSet) });
export const allocateAddress = (tags) => call("AllocateAddress", { TagSpecification: tagSpec("elastic-ip", tags) }).then(addressFromXml);
export async function describeAddresses() {
  const r = await call("DescribeAddresses");
  return asList(r.addressesSet?.item).map(addressFromXml);
}
export const associateAddress = (allocationId, instanceId) => call("AssociateAddress", { AllocationId: allocationId, InstanceId: instanceId });
export const disassociateAddress = (associationId) => call("DisassociateAddress", { AssociationId: associationId });
export const releaseAddress = (allocationId) => call("ReleaseAddress", { AllocationId: allocationId });

// ── network interfaces ──────────────────────────────────────────────────
const eniFromXml = (x) => ({ ...x, Tags: tagsFromXml(x.tagSet), Groups: asList(x.groupSet?.item) });
export const createNetworkInterface = (subnetId, description, securityGroupIds, tags) => call("CreateNetworkInterface", { SubnetId: subnetId, Description: description, SecurityGroupId: securityGroupIds, TagSpecification: tagSpec("network-interface", tags) }).then(eniFromXml);
export async function describeNetworkInterfaces() {
  const r = await call("DescribeNetworkInterfaces");
  return asList(r.networkInterfaceSet?.item).map(eniFromXml);
}
export const deleteNetworkInterface = (id) => call("DeleteNetworkInterface", { NetworkInterfaceId: id });
export const attachNetworkInterface = (eniId, instanceId, deviceIndex) => call("AttachNetworkInterface", { NetworkInterfaceId: eniId, InstanceId: instanceId, DeviceIndex: deviceIndex });
export const detachNetworkInterface = (attachmentId) => call("DetachNetworkInterface", { AttachmentId: attachmentId });

// ── security groups ──────────────────────────────────────────────────
const sgFromXml = (x) => ({
  ...x, GroupId: x.groupId, GroupName: x.groupName, GroupDescription: x.groupDescription, VpcId: x.vpcId,
  Tags: tagsFromXml(x.tagSet),
  IpPermissions: asList(x.ipPermissions?.item).map(permFromXml),
  IpPermissionsEgress: asList(x.ipPermissionsEgress?.item).map(permFromXml),
});
export const createSecurityGroup = (name, description, tags) => call("CreateSecurityGroup", { GroupName: name, GroupDescription: description, TagSpecification: tagSpec("security-group", tags) }).then((r) => r.groupId);
export async function describeSecurityGroups() {
  const r = await call("DescribeSecurityGroups");
  return asList(r.securityGroupInfo?.item).map(sgFromXml);
}
export const describeSecurityGroup = (id) => call("DescribeSecurityGroups", { GroupId: [id] }).then((r) => { const xs = asList(r.securityGroupInfo?.item).map(sgFromXml); return xs[0]; });
export const deleteSecurityGroup = (id) => call("DeleteSecurityGroup", { GroupId: id });
const permParams = (perms) => ({ IpPermissions: (perms || []).map((p) => ({ IpProtocol: p.IpProtocol, ...(p.FromPort !== undefined && p.FromPort !== "" ? { FromPort: p.FromPort, ToPort: p.ToPort } : {}), IpRanges: p.cidr ? [{ CidrIp: p.cidr, Description: p.description }] : undefined, Groups: p.groupId ? [{ GroupId: p.groupId }] : undefined })) });
export const authorizeIngress = (groupId, perms) => call("AuthorizeSecurityGroupIngress", { GroupId: groupId, ...permParams(perms) });
export const authorizeEgress = (groupId, perms) => call("AuthorizeSecurityGroupEgress", { GroupId: groupId, ...permParams(perms) });
export const revokeIngress = (groupId, ruleIds) => call("RevokeSecurityGroupIngress", { GroupId: groupId, SecurityGroupRuleId: ruleIds });
export const revokeEgress = (groupId, ruleIds) => call("RevokeSecurityGroupEgress", { GroupId: groupId, SecurityGroupRuleId: ruleIds });

// ── placement groups ────────────────────────────────────────────────────
const pgFromXml = (x) => ({ ...x, Tags: tagsFromXml(x.tagSet) });
export const createPlacementGroup = (name, strategy, partitionCount, tags) => call("CreatePlacementGroup", { GroupName: name, Strategy: strategy, PartitionCount: partitionCount, TagSpecification: tagSpec("placement-group", tags) }).then(pgFromXml);
export async function describePlacementGroups() {
  const r = await call("DescribePlacementGroups");
  return asList(r.placementGroupSet?.item).map(pgFromXml);
}
export const deletePlacementGroup = (name) => call("DeletePlacementGroup", { GroupName: name });

// ── launch templates ────────────────────────────────────────────────────
const ltFromXml = (x) => ({ ...x, Tags: tagsFromXml(x.tagSet) });
export const createLaunchTemplate = (name, data, versionDescription, tags) => call("CreateLaunchTemplate", { LaunchTemplateName: name, LaunchTemplateData: data, VersionDescription: versionDescription, TagSpecification: tagSpec("launch-template", tags) }).then((r) => ltFromXml(r.launchTemplate));
export async function describeLaunchTemplates() {
  const r = await call("DescribeLaunchTemplates");
  return asList(r.launchTemplates?.item).map(ltFromXml);
}
export const deleteLaunchTemplate = (id) => call("DeleteLaunchTemplate", { LaunchTemplateId: id });
const ltvFromXml = (x) => ({ ...x, DefaultVersion: x.defaultVersion === "true" });
export const createLaunchTemplateVersion = (id, sourceVersion, data, versionDescription) =>
  call("CreateLaunchTemplateVersion", { LaunchTemplateId: id, SourceVersion: sourceVersion, LaunchTemplateData: data, VersionDescription: versionDescription }).then((r) => ltvFromXml(r.launchTemplateVersion));
export async function describeLaunchTemplateVersions(id) {
  const r = await call("DescribeLaunchTemplateVersions", { LaunchTemplateId: id });
  return asList(r.launchTemplateVersionSet?.item).map(ltvFromXml);
}
export const modifyLaunchTemplate = (id, defaultVersion) => call("ModifyLaunchTemplate", { LaunchTemplateId: id, DefaultVersion: defaultVersion }).then((r) => ltFromXml(r.launchTemplate));

// ── tags (generic) ──────────────────────────────────────────────────────
export const createTags = (resourceIds, tags) => call("CreateTags", { ResourceId: resourceIds, Tag: tagsToArray(tags) });
export const deleteTags = (resourceIds, tagKeys) => call("DeleteTags", { ResourceId: resourceIds, Tag: (tagKeys || []).map((Key) => ({ Key })) });
export async function describeTags() {
  const r = await call("DescribeTags");
  return asList(r.tagSet?.item);
}

// ── account-wide EBS encryption defaults ────────────────────────────────
export const getEbsEncryptionByDefault = () => call("GetEbsEncryptionByDefault").then((r) => r.ebsEncryptionByDefault === "true");
export const enableEbsEncryptionByDefault = () => call("EnableEbsEncryptionByDefault");
export const disableEbsEncryptionByDefault = () => call("DisableEbsEncryptionByDefault");
export const getEbsDefaultKmsKeyId = () => call("GetEbsDefaultKmsKeyId").then((r) => r.kmsKeyId);
export const modifyEbsDefaultKmsKeyId = (kmsKeyId) => call("ModifyEbsDefaultKmsKeyId", { KmsKeyId: kmsKeyId });
export const resetEbsDefaultKmsKeyId = () => call("ResetEbsDefaultKmsKeyId");

export const b64 = (s) => btoa(unescape(encodeURIComponent(s)));

// ── the one real CloudWatch metric (StatusCheckFailed) + alarms on it ───
// Real AWS's EC2 console calls straight into CloudWatch for this tab; Vyomi does the same
// native call rather than duplicating CloudWatch's engine (core/cloudwatch_core.py).
const CW = (op, payload = {}) => awsJson("monitoring", `GraniteServiceVersion20100801.${op}`, payload);
export const STATUS_CHECK_METRICS = ["StatusCheckFailed", "StatusCheckFailed_Instance", "StatusCheckFailed_System"];
const statusCheckDims = (instanceId) => [{ Name: "InstanceId", Value: instanceId }];

export const describeStatusCheckAlarms = (instanceId) =>
  Promise.all(STATUS_CHECK_METRICS.map((m) => CW("DescribeAlarmsForMetric", { Namespace: "AWS/EC2", MetricName: m, Dimensions: statusCheckDims(instanceId) })
    .then((r) => r.MetricAlarms || []))).then((lists) => lists.flat());

export const getStatusCheckMetric = (instanceId, metricName, minutes = 30) => {
  const end = new Date(), start = new Date(end - minutes * 60_000);
  return CW("GetMetricStatistics", {
    Namespace: "AWS/EC2", MetricName: metricName, Dimensions: statusCheckDims(instanceId),
    StartTime: start.toISOString(), EndTime: end.toISOString(), Period: 60, Statistics: ["Maximum"],
  }).then((r) => (r.Datapoints || []).sort((a, b) => new Date(a.Timestamp) - new Date(b.Timestamp)));
};

export const putStatusCheckAlarm = (instanceId, { alarmName, metricName, comparison, threshold, evaluationPeriods, snsArn }) =>
  CW("PutMetricAlarm", {
    AlarmName: alarmName, Namespace: "AWS/EC2", MetricName: metricName, Dimensions: statusCheckDims(instanceId),
    Statistic: "Maximum", Period: 60, EvaluationPeriods: evaluationPeriods, DatapointsToAlarm: evaluationPeriods,
    Threshold: threshold, ComparisonOperator: comparison, AlarmActions: snsArn ? [snsArn] : [],
  });
export const deleteStatusCheckAlarms = (names) => CW("DeleteAlarms", { AlarmNames: names });
