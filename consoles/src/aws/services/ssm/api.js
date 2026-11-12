/* Systems Manager over the native JSON wire (X-Amz-Target AmazonSSM.*). */
import { awsJson } from "../../../common/wire.js";

const call = (op, body) => awsJson("ssm", `AmazonSSM.${op}`, body, { version: "1.1" });

const paginate = async (op, body, key) => {
  const out = [];
  let token;
  do {
    const r = await call(op, { ...body, MaxResults: 50, ...(token ? { NextToken: token } : {}) });
    out.push(...(r[key] || []));
    token = r.NextToken;
  } while (token);
  return out;
};

// ── Parameter Store ─────────────────────────────────────────────────────────
export const putParameter = (input) => call("PutParameter", input);
export const getParameter = (name, withDecryption = true) => call("GetParameter", { Name: name, WithDecryption: withDecryption }).then((r) => r.Parameter);
export const listParameters = () => paginate("DescribeParameters", {}, "Parameters");
export const deleteParameter = (name) => call("DeleteParameter", { Name: name });
export const getParameterHistory = (name) => call("GetParameterHistory", { Name: name, WithDecryption: true, MaxResults: 50 }).then((r) => r.Parameters || []);
export const labelParameterVersion = (name, version, labels) => call("LabelParameterVersion", { Name: name, ParameterVersion: version, Labels: labels });

export const listTagsForResource = (resourceType, id) => call("ListTagsForResource", { ResourceType: resourceType, ResourceId: id }).then((r) => r.TagList || []);
export const addTagsToResource = (resourceType, id, tags) => call("AddTagsToResource", { ResourceType: resourceType, ResourceId: id, Tags: tags });
export const removeTagsFromResource = (resourceType, id, keys) => call("RemoveTagsFromResource", { ResourceType: resourceType, ResourceId: id, TagKeys: keys });

// ── Documents ────────────────────────────────────────────────────────────────
export const createDocument = (input) => call("CreateDocument", input).then((r) => r.DocumentDescription);
export const getDocument = (name, opts = {}) => call("GetDocument", { Name: name, ...opts });
export const describeDocument = (name) => call("DescribeDocument", { Name: name }).then((r) => r.Document);
export const listDocuments = (filters) => paginate("ListDocuments", filters ? { Filters: filters } : {}, "DocumentIdentifiers");
export const listDocumentVersions = (name) => call("ListDocumentVersions", { Name: name, MaxResults: 50 }).then((r) => r.DocumentVersions || []);
export const updateDocument = (name, content, opts = {}) => call("UpdateDocument", { Name: name, Content: content, ...opts }).then((r) => r.DocumentDescription);
export const updateDocumentDefaultVersion = (name, version) => call("UpdateDocumentDefaultVersion", { Name: name, DocumentVersion: version });
export const deleteDocument = (name) => call("DeleteDocument", { Name: name });

// ── Run Command ──────────────────────────────────────────────────────────────
export const sendCommand = (input) => call("SendCommand", input).then((r) => r.Command);
export const listCommands = () => paginate("ListCommands", {}, "Commands");
export const getCommandInvocation = (commandId, instanceId) => call("GetCommandInvocation", { CommandId: commandId, InstanceId: instanceId });
export const listCommandInvocations = (commandId) => call("ListCommandInvocations", { CommandId: commandId, Details: true }).then((r) => r.CommandInvocations || []);
export const cancelCommand = (commandId) => call("CancelCommand", { CommandId: commandId });
export const listCommandDocuments = () => listDocuments([{ Key: "DocumentType", Values: ["Command"] }]);

// ── State Manager (associations) ────────────────────────────────────────────
export const createAssociation = (input) => call("CreateAssociation", input).then((r) => r.AssociationDescription);
export const describeAssociation = (id) => call("DescribeAssociation", { AssociationId: id }).then((r) => r.AssociationDescription);
export const listAssociations = () => paginate("ListAssociations", {}, "Associations");
export const deleteAssociation = (id) => call("DeleteAssociation", { AssociationId: id });

// ── Maintenance windows ─────────────────────────────────────────────────────
export const createMaintenanceWindow = (input) => call("CreateMaintenanceWindow", input);
export const getMaintenanceWindow = (id) => call("GetMaintenanceWindow", { WindowId: id });
export const listMaintenanceWindows = () => paginate("DescribeMaintenanceWindows", {}, "WindowIdentities");
export const updateMaintenanceWindow = (id, patch) => call("UpdateMaintenanceWindow", { WindowId: id, ...patch });
export const deleteMaintenanceWindow = (id) => call("DeleteMaintenanceWindow", { WindowId: id });
export const registerWindowTarget = (id, input) => call("RegisterTargetWithMaintenanceWindow", { WindowId: id, ...input }).then((r) => r.WindowTargetId);
export const describeWindowTargets = (id) => call("DescribeMaintenanceWindowTargets", { WindowId: id, MaxResults: 50 }).then((r) => r.Targets || []);
export const deregisterWindowTarget = (id, targetId) => call("DeregisterTargetFromMaintenanceWindow", { WindowId: id, WindowTargetId: targetId });

// ── Patch baselines ──────────────────────────────────────────────────────────
export const createPatchBaseline = (input) => call("CreatePatchBaseline", input);
export const getPatchBaseline = (id) => call("GetPatchBaseline", { BaselineId: id });
export const listPatchBaselines = () => paginate("DescribePatchBaselines", {}, "BaselineIdentities");
export const deletePatchBaseline = (id) => call("DeletePatchBaseline", { BaselineId: id });
