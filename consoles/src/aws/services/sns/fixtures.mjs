/* UI-conformance fixtures for SNS (native Query-protocol wire). See s3/fixtures.mjs. */
const Q = (action, params) => ({
  svc: "sns",
  headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8" },
  body: new URLSearchParams({ Action: action, ...params }).toString(),
});
const arnOf = (name) => `arn:aws:sns:us-east-1:123456789012:${name}`;

export default {
  "sns-topic": async (wire) => { await wire("POST", "/", Q("CreateTopic", { Name: "uic-topic" })).catch(() => {}); return "uic-topic"; },
  "live-topic": async (wire, uniq) => { await wire("POST", "/", Q("CreateTopic", { Name: uniq })); return uniq; },
  "live-subscription": async (wire, uniq) => {
    // sqs confirms immediately (no pending handshake), so ListSubscriptions reports the
    // real SubscriptionArn right away — "PendingConfirmation" is what AWS shows for an
    // unconfirmed email/http subscription, by design (there's no stable ARN yet).
    const topic = `${uniq}-topic`;
    await wire("POST", "/", Q("CreateTopic", { Name: topic }));
    const r = await wire("POST", "/", Q("Subscribe", {
      TopicArn: arnOf(topic), Protocol: "sqs", Endpoint: `arn:aws:sqs:us-east-1:123456789012:${uniq}-queue`, ReturnSubscriptionArn: "true",
    }));
    const m = /<SubscriptionArn>([^<]+)<\/SubscriptionArn>/.exec(r);
    return m[1].split(":").pop();
  },
  "live-platform-app": async (wire, uniq) => {
    await wire("POST", "/", Q("CreatePlatformApplication", {
      Name: uniq, Platform: "GCM", "Attributes.entry.1.key": "PlatformCredential", "Attributes.entry.1.value": "vyomi-demo-credential",
    }));
    return uniq;
  },
};
