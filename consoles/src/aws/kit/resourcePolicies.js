/* Registry for the shared ResourcePolicyTab: kind -> how that service reads / writes its resource-based policy over its NATIVE API.
 *   title / description / noun   text of the tab (as the real console words it)
 *   service                      IAM service prefix of the verbatim catalog the Action picker uses
 *   principals                   "none" for services whose policy has no Principal element
 *   capId                        capability-registry id (kit/Capability.jsx) when the service has one
 *   load(args) -> policy text    save(args, text)    remove(args)  (omit when the service cannot delete the policy)
 * Services whose policy lives elsewhere (Lambda AddPermission statements, KMS key policy with admin/user roles) have their own tab; see
 * docs/architecture/v4.0/branches/iam-resource-tabs.md. */
import * as s3 from "../services/s3/api.js";
import * as sqs from "../services/sqs/api.js";
import * as sns from "../services/sns/api.js";
import * as sm from "../services/secretsmanager/api.js";
import * as ecr from "../services/ecr/api.js";
import * as backup from "../services/backup/api.js";
import * as eb from "../services/eventbridge/api.js";
import * as apigw from "../services/apigateway/api.js";

const unescapeApigw = (p) => { // API Gateway returns the policy as an escaped string (\" and %22)
  if (!p) return "";
  try { JSON.parse(p); return p; } catch { /* fall through */ }
  try { return decodeURIComponent(p).replace(/\\"/g, '"').replace(/\\\\/g, "\\"); } catch { return p.replace(/\\"/g, '"'); }
};

export const RESOURCE_POLICIES = {
  "s3-bucket": {
    title: "Bucket policy", noun: "Bucket policy", service: "s3", capId: "s3.bucket.policy",
    description: "The bucket policy, written in JSON, provides access to the objects stored in the bucket.", empty: "No policy to display.",
    defaultResources: ({ bucket }) => [`arn:aws:s3:::${bucket}`, `arn:aws:s3:::${bucket}/*`],
    load: async ({ bucket }) => (await s3.getPolicy(bucket)).policy,
    save: ({ bucket }, text) => s3.putPolicy(bucket, text),
    remove: ({ bucket }) => s3.deletePolicy(bucket),
  },
  "sqs-queue": {
    title: "Access policy", noun: "Access policy", service: "sqs", capId: "sqs.queue.attributes",
    description: "Defines who can send messages to and receive messages from this queue.", empty: "No policy attached. Only the queue owner can send and receive messages.",
    defaultResources: ({ arn }) => [arn],
    load: async ({ url }) => (await sqs.getQueueAttributes(url)).Policy,
    save: ({ url }, text) => sqs.setQueueAttributes(url, { Policy: text }),
    remove: ({ url }) => sqs.setQueueAttributes(url, { Policy: "" }),
  },
  "sns-topic": {
    title: "Access policy", noun: "Access policy", service: "sns", capId: "sns.topic.access-policy",
    description: "Defines who can publish to and subscribe to this topic.", empty: "No access policy.",
    defaultResources: ({ arn }) => [arn],
    load: async ({ arn }) => (await sns.getTopicAttributes(arn)).Policy,
    save: ({ arn }, text) => sns.setTopicAttribute(arn, "Policy", text),
  },
  "secret": {
    title: "Resource permissions", noun: "Resource permissions", service: "secretsmanager", capId: "secretsmanager.secret.resource-policy",
    description: "Attach a resource-based policy to this secret to control who can access it.", empty: "No resource policy attached.",
    defaultResources: () => ["*"],
    load: ({ name }) => sm.getResourcePolicy(name),
    save: ({ name }, text) => sm.putResourcePolicy(name, text),
    remove: ({ name }) => sm.deleteResourcePolicy(name),
  },
  "ecr-repository": {
    title: "Repository policy", noun: "Repository policy", service: "ecr",
    description: "Resource policy controlling who can pull and push images in this repository.", empty: "No repository policy.",
    load: async ({ name }) => (await ecr.getRepoPolicy(name))?.policyText,
    save: ({ name }, text) => ecr.setRepoPolicy(name, text),
    remove: ({ name }) => ecr.deleteRepoPolicy(name),
  },
  "backup-vault": {
    title: "Backup vault access policy", noun: "Access policy", service: "backup",
    description: "Resource-based policy that controls access to this backup vault.", empty: "No access policy is set on this vault.",
    defaultResources: () => ["*"],
    load: async ({ name }) => (await backup.getVaultAccessPolicy(name))?.Policy,
    save: ({ name }, text) => backup.putVaultAccessPolicy(name, text),
  },
  "eventbridge-bus": {
    title: "Resource-based policy", noun: "Event bus policy", service: "events", capId: "eventbridge.bus.resource-policy",
    description: "Evaluated on cross-account PutEvents. An account needs an explicit events:PutEvents Allow.", empty: "No policy. Only this account can put events to the bus.",
    defaultResources: ({ arn }) => [arn],
    load: async ({ name }) => (await eb.describeEventBus(name)).Policy,
    save: ({ name }, text) => eb.updateEventBusConfig(name, { Policy: text }),
  },
  "apigw-rest": {
    title: "Resource policy", noun: "Resource policy", service: "execute-api",
    description: "A resource policy controls who can invoke this API (cross-account, source IP, VPC endpoint).", empty: "No resource policy. Any caller authorised by the method can invoke the API.",
    defaultResources: ({ arn }) => [arn],
    load: async ({ id }) => unescapeApigw((await apigw.getRestApi(id)).policy),
    save: ({ id }, text) => apigw.updateRestApi(id, [{ op: "replace", path: "/policy", value: text }]),
    remove: ({ id }) => apigw.updateRestApi(id, [{ op: "replace", path: "/policy", value: "" }]),
  },
};
