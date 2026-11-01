/* AWS CloudFormation over the native Query protocol (POST / with Action=<Op>, XML
 * response) — the same wire core/cloudformation_core.py proves against in
 * tests/conformance/test_cloudformation_core.py. */
import { awsQuery, asList } from "../../../common/wire.js";

const call = (action, params = {}) => awsQuery("cloudformation", action, params);
const result = (resp, action) => resp[`${action}Response`]?.[`${action}Result`] || {};

function listParams(values, prefix) {
  const out = {};
  values.forEach((v, i) => { out[`${prefix}.member.${i + 1}`] = v; });
  return out;
}
function paramsOf(parameters = []) {
  const out = {};
  parameters.forEach((p, i) => {
    out[`Parameters.member.${i + 1}.ParameterKey`] = p.key;
    out[`Parameters.member.${i + 1}.ParameterValue`] = p.value ?? "";
  });
  return out;
}
function tagsOf(tags = [], prefix = "Tags") {
  const out = {};
  tags.filter((t) => t.key).forEach((t, i) => {
    out[`${prefix}.member.${i + 1}.Key`] = t.key;
    out[`${prefix}.member.${i + 1}.Value`] = t.value ?? "";
  });
  return out;
}

// ── stacks ───────────────────────────────────────────────────────────────────
export async function listStacks(statusFilter) {
  const r = result(await call("ListStacks", statusFilter?.length ? listParams(statusFilter, "StackStatusFilter") : {}), "ListStacks");
  return asList(r.StackSummaries?.member);
}
export async function describeStack(name) {
  const r = result(await call("DescribeStacks", { StackName: name }), "DescribeStacks");
  const s = asList(r.Stacks?.member)[0];
  if (!s) return s;
  return {
    ...s,
    Tags: Object.fromEntries(asList(s.Tags?.member).map((t) => [t.Key, t.Value])),
    Parameters: Object.fromEntries(asList(s.Parameters?.member).map((p) => [p.ParameterKey, p.ParameterValue])),
    Outputs: asList(s.Outputs?.member),
    Capabilities: asList(s.Capabilities?.member),
  };
}
export async function createStack({ name, templateBody, templateUrl, parameters = [], tags = [], capabilities = [], onFailure, disableRollback, terminationProtection, roleArn, timeoutInMinutes }) {
  const r = result(await call("CreateStack", {
    StackName: name, ...(templateUrl ? { TemplateURL: templateUrl } : { TemplateBody: templateBody }),
    ...paramsOf(parameters), ...tagsOf(tags), ...listParams(capabilities, "Capabilities"),
    ...(onFailure ? { OnFailure: onFailure } : {}), ...(disableRollback ? { DisableRollback: "true" } : {}),
    ...(terminationProtection ? { EnableTerminationProtection: "true" } : {}), ...(roleArn ? { RoleARN: roleArn } : {}),
    ...(timeoutInMinutes ? { TimeoutInMinutes: String(timeoutInMinutes) } : {}),
  }), "CreateStack");
  return r.StackId;
}
export async function updateStack({ name, templateBody, templateUrl, usePreviousTemplate, parameters = [], tags = [], capabilities = [] }) {
  const r = result(await call("UpdateStack", {
    StackName: name, ...(usePreviousTemplate ? { UsePreviousTemplate: "true" } : (templateUrl ? { TemplateURL: templateUrl } : { TemplateBody: templateBody })),
    ...paramsOf(parameters), ...tagsOf(tags), ...listParams(capabilities, "Capabilities"),
  }), "UpdateStack");
  return r.StackId;
}
export const deleteStack = (name) => call("DeleteStack", { StackName: name });
export const updateTerminationProtection = (name, enable) => call("UpdateTerminationProtection", { StackName: name, EnableTerminationProtection: enable ? "true" : "false" });
export const continueUpdateRollback = (name) => call("ContinueUpdateRollback", { StackName: name });
export async function getTemplate(name) { return result(await call("GetTemplate", { StackName: name }), "GetTemplate").TemplateBody || ""; }
export async function validateTemplate(templateBody, templateUrl) {
  const r = result(await call("ValidateTemplate", templateUrl ? { TemplateURL: templateUrl } : { TemplateBody: templateBody }), "ValidateTemplate");
  return { ...r, Parameters: asList(r.Parameters?.member), Capabilities: asList(r.Capabilities?.member) };
}

export async function describeStackEvents(name) {
  const r = result(await call("DescribeStackEvents", { StackName: name }), "DescribeStackEvents");
  return asList(r.StackEvents?.member);
}
export async function describeStackResources(name) {
  const r = result(await call("DescribeStackResources", { StackName: name }), "DescribeStackResources");
  return asList(r.StackResources?.member);
}
export async function listStackResources(name) {
  const r = result(await call("ListStackResources", { StackName: name }), "ListStackResources");
  return asList(r.StackResourceSummaries?.member);
}
export async function listExports() {
  const r = result(await call("ListExports"), "ListExports");
  return asList(r.Exports?.member);
}

// ── change sets ──────────────────────────────────────────────────────────────
export async function createChangeSet({ stackName, changeSetName, templateBody, changeSetType, parameters = [], capabilities = [], description }) {
  const r = result(await call("CreateChangeSet", {
    StackName: stackName, ChangeSetName: changeSetName, TemplateBody: templateBody,
    ...(changeSetType ? { ChangeSetType: changeSetType } : {}), ...paramsOf(parameters), ...listParams(capabilities, "Capabilities"),
    ...(description ? { Description: description } : {}),
  }), "CreateChangeSet");
  return r.Id;
}
export async function describeChangeSet(changeSetName, stackName) {
  return result(await call("DescribeChangeSet", { ChangeSetName: changeSetName, StackName: stackName }), "DescribeChangeSet");
}
export const executeChangeSet = (changeSetName, stackName) => call("ExecuteChangeSet", { ChangeSetName: changeSetName, StackName: stackName });
export const deleteChangeSet = (changeSetName, stackName) => call("DeleteChangeSet", { ChangeSetName: changeSetName, StackName: stackName });
export async function listChangeSets(stackName) {
  const r = result(await call("ListChangeSets", { StackName: stackName }), "ListChangeSets");
  return asList(r.Summaries?.member);
}

// ── drift ────────────────────────────────────────────────────────────────────
export async function detectStackDrift(name) { return result(await call("DetectStackDrift", { StackName: name }), "DetectStackDrift").StackDriftDetectionId; }
export async function describeDriftStatus(id) { return result(await call("DescribeStackDriftDetectionStatus", { StackDriftDetectionId: id }), "DescribeStackDriftDetectionStatus"); }
export async function describeResourceDrifts(name) {
  const r = result(await call("DescribeStackResourceDrifts", { StackName: name }), "DescribeStackResourceDrifts");
  return asList(r.StackResourceDrifts?.member);
}

// ── stack sets / refactors ────────────────────────────────────────────────────
export async function createStackSet({ name, templateBody, description, permissionModel }) {
  const r = result(await call("CreateStackSet", { StackSetName: name, TemplateBody: templateBody, ...(description ? { Description: description } : {}), ...(permissionModel ? { PermissionModel: permissionModel } : {}) }), "CreateStackSet");
  return r.StackSetId;
}
export async function listStackSets() {
  const r = result(await call("ListStackSets"), "ListStackSets");
  return asList(r.Summaries?.member);
}
export async function describeStackSet(name) { return result(await call("DescribeStackSet", { StackSetName: name }), "DescribeStackSet").StackSet; }
export const deleteStackSet = (name) => call("DeleteStackSet", { StackSetName: name });

export async function listStackRefactors() {
  const r = result(await call("ListStackRefactors"), "ListStackRefactors");
  return asList(r.StackRefactorSummaries?.member);
}
export async function createStackRefactor({ mappings = [], description } = {}) {
  const params = description ? { Description: description } : {};
  mappings.forEach((m, i) => {
    params[`ResourceMappings.member.${i + 1}.Source.StackName`] = m.sourceStack;
    params[`ResourceMappings.member.${i + 1}.Source.LogicalResourceId`] = m.sourceLogicalId;
    params[`ResourceMappings.member.${i + 1}.Destination.StackName`] = m.destStack;
    params[`ResourceMappings.member.${i + 1}.Destination.LogicalResourceId`] = m.destLogicalId;
  });
  const r = result(await call("CreateStackRefactor", params), "CreateStackRefactor");
  return r.StackRefactorId;
}
export async function describeStackRefactor(id) {
  const r = result(await call("DescribeStackRefactor", { StackRefactorId: id }), "DescribeStackRefactor");
  return { ...r, StackIds: asList(r.StackIds?.member) };
}
export const executeStackRefactor = (id) => call("ExecuteStackRefactor", { StackRefactorId: id });

// ── IaC generator (resource scans + generated templates) ──────────────────────
function identifierToMap(ri) {
  return Object.fromEntries(asList(ri?.entry).map((e) => [e.key, e.value]));
}
function identifierParams(map, prefix) {
  const out = {};
  Object.entries(map).forEach(([k, v], i) => {
    out[`${prefix}.entry.${i + 1}.key`] = k;
    out[`${prefix}.entry.${i + 1}.value`] = v;
  });
  return out;
}
export async function startResourceScan() {
  return result(await call("StartResourceScan"), "StartResourceScan").ResourceScanId;
}
export async function listResourceScans() {
  const r = result(await call("ListResourceScans"), "ListResourceScans");
  return asList(r.ResourceScanSummaries?.member);
}
export async function describeResourceScan(scanId) {
  const r = result(await call("DescribeResourceScan", { ResourceScanId: scanId }), "DescribeResourceScan");
  return { ...r, ResourceTypes: asList(r.ResourceTypes?.member) };
}
export async function listResourceScanResources(scanId, typePrefix) {
  const r = result(await call("ListResourceScanResources", { ResourceScanId: scanId, ...(typePrefix ? { ResourceTypePrefix: typePrefix } : {}) }), "ListResourceScanResources");
  return asList(r.Resources?.member).map((m) => ({
    ResourceType: m.ResourceType, Identifier: identifierToMap(m.ResourceIdentifier), ManagedByStack: m.ManagedByStack === "true",
  }));
}
export async function createGeneratedTemplate(name, resources = []) {
  const params = { GeneratedTemplateName: name };
  resources.forEach((res, i) => {
    params[`Resources.member.${i + 1}.ResourceType`] = res.ResourceType;
    Object.assign(params, identifierParams(res.Identifier, `Resources.member.${i + 1}.ResourceIdentifier`));
  });
  const r = result(await call("CreateGeneratedTemplate", params), "CreateGeneratedTemplate");
  return r.GeneratedTemplateId;
}
export async function listGeneratedTemplates() {
  const r = result(await call("ListGeneratedTemplates"), "ListGeneratedTemplates");
  return asList(r.Summaries?.member);
}
export async function describeGeneratedTemplate(name) {
  const r = result(await call("DescribeGeneratedTemplate", { GeneratedTemplateName: name }), "DescribeGeneratedTemplate");
  return { ...r, Resources: asList(r.Resources?.member) };
}
export async function getGeneratedTemplate(name) {
  return result(await call("GetGeneratedTemplate", { GeneratedTemplateName: name }), "GetGeneratedTemplate").TemplateBody || "";
}
export const deleteGeneratedTemplate = (name) => call("DeleteGeneratedTemplate", { GeneratedTemplateName: name });

// ── registry (extensions) ────────────────────────────────────────────────────
export async function listTypes() {
  const r = result(await call("ListTypes", { Visibility: "PUBLIC", Type: "RESOURCE" }), "ListTypes");
  return asList(r.TypeSummaries?.member);
}
export async function describeType(typeName) {
  return result(await call("DescribeType", { TypeName: typeName }), "DescribeType");
}

// ── hooks (registry Type=HOOK): registered + configured with a required-tag policy,
// enforced for real on CreateStack/UpdateStack/DeleteStack (core/cloudformation_core.py
// _run_hooks). ────────────────────────────────────────────────────────────────
function hookTypeSummary(m) {
  return {
    TypeName: m.TypeName,
    Description: m.Description || "",
    FailureMode: m.FailureMode || "WARN",
    TargetOperations: asList(m.TargetOperations?.member),
    TargetStacks: m.TargetStacks === "ALL" ? "ALL" : (m.TargetStacks ? m.TargetStacks.split(",").filter(Boolean) : []),
    RequiredTagKeys: m.RequiredTagKeys ? m.RequiredTagKeys.split(",").filter(Boolean) : [],
    Enabled: m.IsActivated === "true",
    LastUpdated: m.LastUpdated,
    TimeCreated: m.TimeCreated,
    TypeArn: m.TypeArn,
  };
}
export async function listHooks() {
  const r = result(await call("ListTypes", { Visibility: "PRIVATE", Type: "HOOK" }), "ListTypes");
  return asList(r.TypeSummaries?.member).map(hookTypeSummary);
}
export async function describeHook(typeName) {
  const r = result(await call("DescribeType", { Type: "HOOK", TypeName: typeName }), "DescribeType");
  return hookTypeSummary(r);
}
function hookConfiguration({ failureMode, targetOperations = [], targetStacks, requiredTagKeys = [], enabled = true }) {
  return JSON.stringify({
    CloudFormationConfiguration: {
      HookConfiguration: {
        FailureMode: failureMode,
        TargetOperations: targetOperations,
        TargetStacks: targetStacks === "ALL" ? "ALL" : targetStacks,
        Properties: { RequiredTagKeys: requiredTagKeys.join(","), Enabled: enabled ? "true" : "false" },
      },
    },
  });
}
export async function createHook(hook) {
  await call("RegisterType", { Type: "HOOK", TypeName: hook.typeName });
  await call("SetTypeConfiguration", { TypeName: hook.typeName, Configuration: hookConfiguration(hook) });
}
export const setHookEnabled = (hook, enabled) => call("SetTypeConfiguration", { TypeName: hook.TypeName, Configuration: hookConfiguration({
  failureMode: hook.FailureMode, targetOperations: hook.TargetOperations, targetStacks: hook.TargetStacks, requiredTagKeys: hook.RequiredTagKeys, enabled,
}) });
export const deleteHook = (typeName) => call("DeregisterType", { Type: "HOOK", TypeName: typeName });
export async function listHookResults(targetId) {
  const r = result(await call("ListHookResults", targetId ? { TargetId: targetId } : {}), "ListHookResults");
  return asList(r.HookResultSummaries?.member);
}
