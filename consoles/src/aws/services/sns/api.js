/* Amazon SNS over the native Query protocol (POST / with Action=<Op>, XML response) —
 * the same wire core/sns_core.py proves against in tests/conformance/test_sns_core.py. */
import { awsQuery, asList } from "../../../common/wire.js";

const call = (action, params = {}) => awsQuery("sns", action, params);
const result = (resp, action) => resp[`${action}Response`]?.[`${action}Result`] || {};

function attrsOf(node) {
  if (!node) return {};
  return Object.fromEntries(asList(node.entry).map((e) => [e.key, e.value ?? ""]));
}
function attributesParams(attrs) {
  const out = {};
  Object.entries(attrs).forEach(([k, v], i) => {
    out[`Attributes.entry.${i + 1}.key`] = k;
    out[`Attributes.entry.${i + 1}.value`] = String(v);
  });
  return out;
}
function tagsParams(tags, prefix = "Tags") {
  const out = {};
  tags.forEach((t, i) => {
    out[`${prefix}.member.${i + 1}.Key`] = t.key;
    out[`${prefix}.member.${i + 1}.Value`] = t.value ?? "";
  });
  return out;
}
function messageAttributeParams(attrs) {
  const out = {};
  attrs.forEach((a, i) => {
    const n = i + 1;
    out[`MessageAttributes.entry.${n}.Name`] = a.name;
    out[`MessageAttributes.entry.${n}.Value.DataType`] = a.type || "String";
    out[`MessageAttributes.entry.${n}.Value.StringValue`] = a.value;
  });
  return out;
}

// ── topics ──────────────────────────────────────────────────────────────────
export async function listTopics() {
  const arns = [];
  let token;
  do {
    const r = result(await call("ListTopics", token ? { NextToken: token } : {}), "ListTopics");
    arns.push(...asList(r.Topics?.member).map((m) => m.TopicArn));
    token = r.NextToken;
  } while (token);
  return arns;
}
export const createTopic = async (name, attrs = {}, tags = []) =>
  result(await call("CreateTopic", { Name: name, ...attributesParams(attrs), ...tagsParams(tags) }), "CreateTopic").TopicArn;
export const deleteTopic = (arn) => call("DeleteTopic", { TopicArn: arn });
export const getTopicAttributes = async (arn) => attrsOf(result(await call("GetTopicAttributes", { TopicArn: arn }), "GetTopicAttributes").Attributes);
export const setTopicAttribute = (arn, name, value) => call("SetTopicAttributes", { TopicArn: arn, AttributeName: name, AttributeValue: value == null ? "" : String(value) });
export const addPermission = (arn, label, accountIds, actions) => call("AddPermission", {
  TopicArn: arn, Label: label,
  ...Object.fromEntries(accountIds.map((a, i) => [`AWSAccountId.member.${i + 1}`, a])),
  ...Object.fromEntries(actions.map((a, i) => [`ActionName.member.${i + 1}`, a])),
});
export const removePermission = (arn, label) => call("RemovePermission", { TopicArn: arn, Label: label });

export async function topicByName(name) {
  const arn = (await listTopics()).find((a) => a.endsWith(`:${name}`));
  if (!arn) { const e = new Error(`Topic ${name} does not exist`); e.code = "NotFound"; e.status = 404; throw e; }
  return arn;
}
export const topicName = (arn) => arn.split(":").pop();

// ── tags + data protection ───────────────────────────────────────────────────
export const tagResource = (arn, tags) => call("TagResource", { ResourceArn: arn, ...tagsParams(tags) });
export const untagResource = (arn, keys) => call("UntagResource", { ResourceArn: arn, ...Object.fromEntries(keys.map((k, i) => [`TagKeys.member.${i + 1}`, k])) });
export const listTagsForResource = async (arn) => asList(result(await call("ListTagsForResource", { ResourceArn: arn }), "ListTagsForResource").Tags?.member);
export const putDataProtectionPolicy = (arn, policy) => call("PutDataProtectionPolicy", { ResourceArn: arn, DataProtectionPolicy: policy });
export const getDataProtectionPolicy = async (arn) => result(await call("GetDataProtectionPolicy", { ResourceArn: arn }), "GetDataProtectionPolicy").DataProtectionPolicy || "";

// ── subscriptions ─────────────────────────────────────────────────────────────
function subMember(m) {
  const pending = m.SubscriptionArn === "PendingConfirmation";
  return { arn: m.SubscriptionArn, pending, topicArn: m.TopicArn, protocol: m.Protocol, endpoint: m.Endpoint, owner: m.Owner };
}
export async function listSubscriptions() {
  const out = [];
  let token;
  do {
    const r = result(await call("ListSubscriptions", token ? { NextToken: token } : {}), "ListSubscriptions");
    out.push(...asList(r.Subscriptions?.member).map(subMember));
    token = r.NextToken;
  } while (token);
  return out;
}
export async function listSubscriptionsByTopic(arn) {
  const out = [];
  let token;
  do {
    const r = result(await call("ListSubscriptionsByTopic", { TopicArn: arn, ...(token ? { NextToken: token } : {}) }), "ListSubscriptionsByTopic");
    out.push(...asList(r.Subscriptions?.member).map(subMember));
    token = r.NextToken;
  } while (token);
  return out;
}
export const subscribe = async (topicArn, protocol, endpoint, attrs = {}) =>
  result(await call("Subscribe", { TopicArn: topicArn, Protocol: protocol, Endpoint: endpoint, ReturnSubscriptionArn: "true", ...attributesParams(attrs) }), "Subscribe").SubscriptionArn;
export const confirmSubscription = (topicArn, token) => call("ConfirmSubscription", { TopicArn: topicArn, Token: token });
export const unsubscribe = (subArn) => call("Unsubscribe", { SubscriptionArn: subArn });
export const getSubscriptionAttributes = async (subArn) => attrsOf(result(await call("GetSubscriptionAttributes", { SubscriptionArn: subArn }), "GetSubscriptionAttributes").Attributes);
export const setSubscriptionAttribute = (subArn, name, value) => call("SetSubscriptionAttributes", { SubscriptionArn: subArn, AttributeName: name, AttributeValue: value == null ? "" : String(value) });
export const subId = (arn) => arn.split(":").pop();

// ── publish ───────────────────────────────────────────────────────────────────
export async function publish({ topicArn, targetArn, phoneNumber, message, subject, messageGroupId, messageDeduplicationId, messageStructure, attributes = [] }) {
  const params = { Message: message, ...messageAttributeParams(attributes) };
  if (topicArn) params.TopicArn = topicArn;
  if (targetArn) params.TargetArn = targetArn;
  if (phoneNumber) params.PhoneNumber = phoneNumber;
  if (subject) params.Subject = subject;
  if (messageStructure) params.MessageStructure = messageStructure;
  if (messageGroupId) params.MessageGroupId = messageGroupId;
  if (messageDeduplicationId) params.MessageDeduplicationId = messageDeduplicationId;
  return result(await call("Publish", params), "Publish");
}

// ── mobile push: platform applications + endpoints ───────────────────────────
function appMember(m) { return { arn: m.PlatformApplicationArn, attributes: attrsOf(m.Attributes) }; }
export async function listPlatformApplications() {
  const out = [];
  let token;
  do {
    const r = result(await call("ListPlatformApplications", token ? { NextToken: token } : {}), "ListPlatformApplications");
    out.push(...asList(r.PlatformApplications?.member).map(appMember));
    token = r.NextToken;
  } while (token);
  return out;
}
export const createPlatformApplication = async (name, platform, credential) =>
  result(await call("CreatePlatformApplication", { Name: name, Platform: platform, "Attributes.entry.1.key": "PlatformCredential", "Attributes.entry.1.value": credential }), "CreatePlatformApplication").PlatformApplicationArn;
export const deletePlatformApplication = (arn) => call("DeletePlatformApplication", { PlatformApplicationArn: arn });
export const getPlatformApplicationAttributes = async (arn) => attrsOf(result(await call("GetPlatformApplicationAttributes", { PlatformApplicationArn: arn }), "GetPlatformApplicationAttributes").Attributes);
export const setPlatformApplicationAttributes = (arn, attrs) => call("SetPlatformApplicationAttributes", { PlatformApplicationArn: arn, ...attributesParams(attrs) });
export const createPlatformEndpoint = async (appArn, token, customUserData) =>
  result(await call("CreatePlatformEndpoint", { PlatformApplicationArn: appArn, Token: token, ...(customUserData ? { CustomUserData: customUserData } : {}) }), "CreatePlatformEndpoint").EndpointArn;
export async function listEndpointsByPlatformApplication(appArn) {
  const out = [];
  let token;
  do {
    const r = result(await call("ListEndpointsByPlatformApplication", { PlatformApplicationArn: appArn, ...(token ? { NextToken: token } : {}) }), "ListEndpointsByPlatformApplication");
    out.push(...asList(r.Endpoints?.member).map((m) => ({ arn: m.EndpointArn, attributes: attrsOf(m.Attributes) })));
    token = r.NextToken;
  } while (token);
  return out;
}
export const deleteEndpoint = (arn) => call("DeleteEndpoint", { EndpointArn: arn });
export const appName = (arn) => arn.split("/").pop();
export const appPlatform = (arn) => arn.split("/")[1];

// ── SMS: attributes, opt-out, sandbox ─────────────────────────────────────────
export async function getSmsAttributes() {
  return attrsOf(result(await call("GetSMSAttributes"), "GetSMSAttributes").attributes);
}
export const setSmsAttributes = (attrs) => {
  const out = {};
  Object.entries(attrs).forEach(([k, v], i) => { out[`attributes.entry.${i + 1}.key`] = k; out[`attributes.entry.${i + 1}.value`] = String(v); });
  return call("SetSMSAttributes", out);
};
export const checkIfPhoneNumberIsOptedOut = async (phone) => result(await call("CheckIfPhoneNumberIsOptedOut", { phoneNumber: phone }), "CheckIfPhoneNumberIsOptedOut").isOptedOut === "true";
export async function listPhoneNumbersOptedOut() {
  const out = [];
  let token;
  do {
    const r = result(await call("ListPhoneNumbersOptedOut", token ? { nextToken: token } : {}), "ListPhoneNumbersOptedOut");
    out.push(...asList(r.phoneNumbers?.member));
    token = r.nextToken;
  } while (token);
  return out;
}
export const optInPhoneNumber = (phone) => call("OptInPhoneNumber", { phoneNumber: phone });
export const createSmsSandboxPhoneNumber = (phone) => call("CreateSMSSandboxPhoneNumber", { PhoneNumber: phone });
export const verifySmsSandboxPhoneNumber = (phone, otp) => call("VerifySMSSandboxPhoneNumber", { PhoneNumber: phone, OneTimePassword: otp });
export const deleteSmsSandboxPhoneNumber = (phone) => call("DeleteSMSSandboxPhoneNumber", { PhoneNumber: phone });
export async function listSmsSandboxPhoneNumbers() {
  const out = [];
  let token;
  do {
    const r = result(await call("ListSMSSandboxPhoneNumbers", token ? { NextToken: token } : {}), "ListSMSSandboxPhoneNumbers");
    out.push(...asList(r.PhoneNumbers?.member).map((m) => ({ phone: m.PhoneNumber, status: m.Status })));
    token = r.NextToken;
  } while (token);
  return out;
}
