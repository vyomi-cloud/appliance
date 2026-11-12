/* Amazon EKS over its native REST-JSON wire (SigV4 scope `eks`) -> core/aws_eks_core.py, plus the AWS Backup wire for
 * "AWS Backup for EKS" (core/backup_vaults_core.py). The only non-AWS call is `kubectl` (Vyomi extension; EKS has no API to run it). */
import { awsRest, awsQuery, asList, pick } from "../../../common/wire.js";

const R = (method, path, opts) => awsRest("eks", method, path, opts);
const B = (method, path, opts) => awsRest("backup", method, path, opts);
const enc = encodeURIComponent;
const q = (o) => Object.fromEntries(Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== ""));

export const ACCOUNT = "123456789012";

// ── clusters ──
export const listClusterNames = () => R("GET", "/clusters").then((r) => r.clusters || []);
export const describeCluster = (name) => R("GET", `/clusters/${enc(name)}`).then((r) => r.cluster);
export async function listClusters() {
  const names = await listClusterNames();
  return (await Promise.all(names.map((n) => describeCluster(n).catch(() => null)))).filter(Boolean);
}
export const createCluster = (body) => R("POST", "/clusters", { body }).then((r) => r.cluster);
export const deleteCluster = (name) => R("DELETE", `/clusters/${enc(name)}`).then((r) => r.cluster);
export const updateClusterVersion = (name, version) => R("POST", `/clusters/${enc(name)}/updates`, { body: { version } }).then((r) => r.update);
export const updateClusterConfig = (name, body) => R("POST", `/clusters/${enc(name)}/update-config`, { body }).then((r) => r.update);
export const listClusterVersions = () => R("GET", "/cluster-versions").then((r) => r.clusterVersions || []);

// ── updates ──
export async function listUpdates(name, scope = {}) {
  const ids = (await R("GET", `/clusters/${enc(name)}/updates`, { query: q(scope) })).updateIds || [];
  return Promise.all(ids.map((id) => describeUpdate(name, id, scope)));
}
export const describeUpdate = (name, id, scope = {}) => R("GET", `/clusters/${enc(name)}/updates/${enc(id)}`, { query: q(scope) }).then((r) => r.update);

// ── managed node groups ──
export async function listNodegroups(cluster) {
  const names = (await R("GET", `/clusters/${enc(cluster)}/node-groups`)).nodegroups || [];
  return Promise.all(names.map((n) => describeNodegroup(cluster, n)));
}
export const describeNodegroup = (c, n) => R("GET", `/clusters/${enc(c)}/node-groups/${enc(n)}`).then((r) => r.nodegroup);
export const createNodegroup = (c, body) => R("POST", `/clusters/${enc(c)}/node-groups`, { body }).then((r) => r.nodegroup);
export const deleteNodegroup = (c, n) => R("DELETE", `/clusters/${enc(c)}/node-groups/${enc(n)}`).then((r) => r.nodegroup);
export const updateNodegroupConfig = (c, n, body) => R("POST", `/clusters/${enc(c)}/node-groups/${enc(n)}/update-config`, { body }).then((r) => r.update);

// ── Fargate profiles ──
export async function listFargateProfiles(cluster) {
  const names = (await R("GET", `/clusters/${enc(cluster)}/fargate-profiles`)).fargateProfileNames || [];
  return Promise.all(names.map((n) => R("GET", `/clusters/${enc(cluster)}/fargate-profiles/${enc(n)}`).then((r) => r.fargateProfile)));
}
export const createFargateProfile = (c, body) => R("POST", `/clusters/${enc(c)}/fargate-profiles`, { body }).then((r) => r.fargateProfile);
export const deleteFargateProfile = (c, n) => R("DELETE", `/clusters/${enc(c)}/fargate-profiles/${enc(n)}`).then((r) => r.fargateProfile);

// ── add-ons ──
export async function listAddons(cluster) {
  const names = (await R("GET", `/clusters/${enc(cluster)}/addons`)).addons || [];
  return Promise.all(names.map((n) => R("GET", `/clusters/${enc(cluster)}/addons/${enc(n)}`).then((r) => r.addon)));
}
export const createAddon = (c, body) => R("POST", `/clusters/${enc(c)}/addons`, { body }).then((r) => r.addon);
export const updateAddon = (c, n, body) => R("PATCH", `/clusters/${enc(c)}/addons/${enc(n)}/update`, { body }).then((r) => r.update);
export const deleteAddon = (c, n) => R("DELETE", `/clusters/${enc(c)}/addons/${enc(n)}`).then((r) => r.addon);
export const describeAddonVersions = (kubernetesVersion, addonName) => R("GET", "/addons/supported-versions", { query: q({ kubernetesVersion, addonName }) }).then((r) => r.addons || []);

// ── access entries ──
export async function listAccessEntries(cluster) {
  const arns = (await R("GET", `/clusters/${enc(cluster)}/access-entries`)).accessEntries || [];
  return Promise.all(arns.map(async (a) => {
    const e = await R("GET", `/clusters/${enc(cluster)}/access-entries/${enc(a)}`).then((r) => r.accessEntry);
    const pol = await R("GET", `/clusters/${enc(cluster)}/access-entries/${enc(a)}/access-policies`).then((r) => r.associatedAccessPolicies || []);
    return { ...e, policies: pol };
  }));
}
export const createAccessEntry = (c, body) => R("POST", `/clusters/${enc(c)}/access-entries`, { body }).then((r) => r.accessEntry);
export const deleteAccessEntry = (c, arn) => R("DELETE", `/clusters/${enc(c)}/access-entries/${enc(arn)}`);
export const associateAccessPolicy = (c, arn, body) => R("POST", `/clusters/${enc(c)}/access-entries/${enc(arn)}/access-policies`, { body });
export const disassociateAccessPolicy = (c, arn, policyArn) => R("DELETE", `/clusters/${enc(c)}/access-entries/${enc(arn)}/access-policies/${enc(policyArn)}`);
export const listAccessPolicies = () => R("GET", "/access-policies").then((r) => r.accessPolicies || []);

// ── OIDC identity providers ──
export async function listIdentityProviders(cluster) {
  const refs = (await R("GET", `/clusters/${enc(cluster)}/identity-provider-configs`)).identityProviderConfigs || [];
  return Promise.all(refs.map((x) => R("POST", `/clusters/${enc(cluster)}/identity-provider-configs/describe`, { body: { identityProviderConfig: x } }).then((r) => r.identityProviderConfig.oidc)));
}
export const associateOidc = (c, oidc) => R("POST", `/clusters/${enc(c)}/identity-provider-configs/associate`, { body: { oidc } });
export const disassociateOidc = (c, name) => R("POST", `/clusters/${enc(c)}/identity-provider-configs/disassociate`, { body: { identityProviderConfig: { type: "oidc", name } } });

// ── tags ──
export const listTags = (arn) => R("GET", `/tags/${enc(arn)}`).then((r) => r.tags || {});
export const tagResource = (arn, tags) => R("POST", `/tags/${enc(arn)}`, { body: { tags } });
export const untagResource = (arn, keys) => R("DELETE", `/tags/${enc(arn)}`, { query: { tagKeys: keys.join(",") } });

// ── Vyomi extension: kubectl (console terminal) ──
export const kubectl = (cluster, command) => R("POST", `/clusters/${enc(cluster)}/vyomi/kubectl`, { body: { command } });

// ── pickers (IAM roles, VPC subnets / security groups through their native wires) ──
export const listRoles = async () => {
  const r = await awsQuery("iam", "ListRoles", {});
  return asList(pick(r.ListRolesResponse?.ListRolesResult?.Roles, "Role")).map((x) => ({ name: x.RoleName, arn: x.Arn }));
};
export const listSubnets = async () => {
  const r = await awsQuery("ec2", "DescribeSubnets", {});
  return asList(r.DescribeSubnetsResponse?.subnetSet?.item).map((x) => ({ id: x.subnetId, vpc: x.vpcId, az: x.availabilityZone, cidr: x.cidrBlock }));
};
export const listSecurityGroups = async () => {
  const r = await awsQuery("ec2", "DescribeSecurityGroups", {});
  return asList(r.DescribeSecurityGroupsResponse?.securityGroupInfo?.item).map((x) => ({ id: x.groupId, vpc: x.vpcId, name: x.groupName }));
};

// ── AWS Backup for EKS (native AWS Backup REST) ──
export const listVaults = () => B("GET", "/backup-vaults").then((r) => r.BackupVaultList || []);
export const createVault = (name) => B("PUT", `/backup-vaults/${enc(name)}`, { body: {} });
export const startBackup = (vault, arn, role) => B("PUT", "/backup-jobs", { body: { BackupVaultName: vault, ResourceArn: arn, IamRoleArn: role } });
export const describeBackupJob = (id) => B("GET", `/backup-jobs/${enc(id)}`);
export const listBackupJobs = () => B("GET", "/backup-jobs").then((r) => r.BackupJobs || []);
export const listRecoveryPointsByResource = (arn) => B("GET", `/resources/${enc(arn)}/recovery-points`).then((r) => r.RecoveryPoints || []);
export const startRestore = (rpArn, role, metadata) => B("PUT", "/restore-jobs", { body: { RecoveryPointArn: rpArn, IamRoleArn: role, Metadata: metadata } });
export const describeRestoreJob = (id) => B("GET", `/restore-jobs/${enc(id)}`);
export const listRestoreJobs = () => B("GET", "/restore-jobs").then((r) => r.RestoreJobs || []);

// Create-or-reuse the recommended trust role (idempotent: a second click must not fail on EntityAlreadyExists).
export const ensureRole = async (name, service) => {
  const existing = (await listRoles()).find((r) => r.name === name);
  if (existing) return existing.arn;
  const r = await awsQuery("iam", "CreateRole", { RoleName: name, AssumeRolePolicyDocument: JSON.stringify({ Version: "2012-10-17", Statement: [{ Effect: "Allow", Principal: { Service: service }, Action: "sts:AssumeRole" }] }) });
  return r.CreateRoleResponse.CreateRoleResult.Role.Arn;
};
