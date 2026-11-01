/* Step Functions over the native JSON wire (X-Amz-Target AWSStepFunctions.*),
 * core/stepfunctions_core.py. */
import { awsJson } from "../../../common/wire.js";

const call = (op, body) => awsJson("stepfunctions", `AWSStepFunctions.${op}`, body);

// Lambda's "Step Functions state machines" cross-link page (lambda/api.js) uses this exact
// placeholder role ARN — Vyomi has no IAM-role-creation flow for Step Functions, so every
// creation path defaults to the same fixed service role.
export const DEFAULT_ROLE_ARN = "arn:aws:iam::123456789012:role/service-role/StepFunctions-vyomi-role";
export const DEFAULT_DEFINITION = JSON.stringify({
  Comment: "A Hello World example of the Amazon States Language using a Pass state",
  StartAt: "HelloWorld",
  States: { HelloWorld: { Type: "Pass", Result: "Hello World!", End: true } },
}, null, 2);

export const listStateMachines = async () => (await call("ListStateMachines", {})).stateMachines || [];
export const describeStateMachine = (stateMachineArn) => call("DescribeStateMachine", { stateMachineArn });
export const createStateMachine = (body) => call("CreateStateMachine", body);
export const updateStateMachine = (body) => call("UpdateStateMachine", body);
export const deleteStateMachine = (stateMachineArn) => call("DeleteStateMachine", { stateMachineArn });
export const validateDefinition = (definition) => call("ValidateStateMachineDefinition", { definition });

export const listVersions = async (stateMachineArn) => (await call("ListStateMachineVersions", { stateMachineArn })).stateMachineVersions || [];
export const publishVersion = (stateMachineArn, description) => call("PublishStateMachineVersion", { stateMachineArn, ...(description ? { description } : {}) });
export const deleteVersion = (stateMachineVersionArn) => call("DeleteStateMachineVersion", { stateMachineVersionArn });

export const listAliases = async (stateMachineArn) => (await call("ListStateMachineAliases", { stateMachineArn })).stateMachineAliases || [];
export const createAlias = (name, routingConfiguration, description) => call("CreateStateMachineAlias", { name, routingConfiguration, ...(description ? { description } : {}) });
export const deleteAlias = (stateMachineAliasArn) => call("DeleteStateMachineAlias", { stateMachineAliasArn });

export const startExecution = (body) => call("StartExecution", body);
export const describeExecution = (executionArn) => call("DescribeExecution", { executionArn });
export const stopExecution = (executionArn) => call("StopExecution", { executionArn });
export const redriveExecution = (executionArn) => call("RedriveExecution", { executionArn });
export const listExecutions = async (stateMachineArn) => (await call("ListExecutions", { stateMachineArn })).executions || [];
export const getExecutionHistory = async (executionArn) => (await call("GetExecutionHistory", { executionArn })).events || [];
export const describeStateMachineForExecution = (executionArn) => call("DescribeStateMachineForExecution", { executionArn });

export const listActivities = async () => (await call("ListActivities", {})).activities || [];
export const describeActivity = (activityArn) => call("DescribeActivity", { activityArn });
export const createActivity = (name) => call("CreateActivity", { name });
export const deleteActivity = (activityArn) => call("DeleteActivity", { activityArn });

export const listTags = async (resourceArn) => (await call("ListTagsForResource", { resourceArn })).tags || [];
export const tagResource = (resourceArn, tags) => call("TagResource", { resourceArn, tags });
export const untagResource = (resourceArn, tagKeys) => call("UntagResource", { resourceArn, tagKeys });

/** `arn:aws:states:region:acct:stateMachine:name` -> `name` (strips a version/alias qualifier). */
export const nameFromArn = (arn) => (arn || "").split(":")[6];
