/* UI-conformance fixtures for Lambda (native REST+JSON wire). See s3/fixtures.mjs. */
const F = "/2015-03-31/functions";
const fn = (name) => ({ FunctionName: name, Runtime: "python3.12", Code: { Source: "def handler(e,c):\n    return {'ok': True}\n" } });

export default {
  "lambda-fn": async (wire) => {
    await wire("POST", F, { svc: "lambda", body: fn("uic-function") }).catch(() => {});
    return "uic-function";
  },
  "live-function": async (wire, uniq) => {
    await wire("POST", F, { svc: "lambda", body: fn(uniq) });
    return uniq;
  },
  "live-web-function": async (wire, uniq) => {
    await wire("POST", F, { svc: "lambda", body: fn(uniq) });
    await wire("POST", `${F}/${uniq}/url`, { svc: "lambda", body: { AuthType: "NONE" } });
    return uniq;
  },
  "live-layer": async (wire, uniq) => {
    await wire("POST", `/2015-03-31/layers/${uniq}/versions`, { svc: "lambda", body: { Content: { Source: "x" }, CompatibleRuntimes: ["python3.12"] } });
    return uniq;
  },
  "live-trigger": async (wire, uniq) => {
    await wire("POST", F, { svc: "lambda", body: fn(uniq) });
    await wire("POST", "/2015-03-31/event-source-mappings", { svc: "lambda", body: { FunctionName: uniq, EventSourceArn: `arn:aws:sqs:us-east-1:123456789012:${uniq}` } });
    return uniq;
  },
};
