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

// ── registry (extensions) ────────────────────────────────────────────────────
export async function listTypes() {
  const r = result(await call("ListTypes", { Visibility: "PUBLIC", Type: "RESOURCE" }), "ListTypes");
  return asList(r.TypeSummaries?.member);
}
export async function describeType(typeName) {
  return result(await call("DescribeType", { TypeName: typeName }), "DescribeType");
}
