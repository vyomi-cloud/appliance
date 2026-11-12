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

  // Vyomi-exclusive console surfaces (see core/lambda_core.py module note above
  // _capacity_providers) — real named-resource CRUD, no simulated runtime underneath.
  "live-application": async (wire, uniq) => {
    await wire("POST", "/2015-03-31/applications", { svc: "lambda", body: { Name: uniq } });
    return uniq;
  },
  "live-capacity-provider": async (wire, uniq) => {
    await wire("POST", "/2015-03-31/capacity-providers", { svc: "lambda", body: { Name: uniq, VpcId: "vpc-uic" } });
    return uniq;
  },
  "live-csc": async (wire, uniq) => {
    await wire("POST", "/2015-03-31/code-signing-configs", { svc: "lambda", body: { Description: uniq } });
    return uniq;
  },
  "live-replica": async (wire, uniq) => {
    await wire("POST", F, { svc: "lambda", body: fn(uniq) });
    await wire("PUT", `${F}/${uniq}/replication`, { svc: "lambda", body: { Regions: ["eu-west-1"] } });
    return uniq;
  },
  "live-microvm-image": async (wire, uniq) => {
    await wire("POST", "/2015-03-31/microvm-images", { svc: "lambda", body: { Name: uniq } });
    return uniq;
  },
  "live-microvm": async (wire, uniq) => {
    await wire("POST", "/2015-03-31/microvm-images", { svc: "lambda", body: { Name: uniq } });
    const r = await wire("POST", "/2015-03-31/microvms", { svc: "lambda", body: { MicrovmImage: uniq } });
    return r.Id;
  },
  "live-network-connector": async (wire, uniq) => {
    await wire("POST", "/2015-03-31/network-connectors", { svc: "lambda", body: { Name: uniq, VpcId: "vpc-uic" } });
    return uniq;
  },
  "live-state-machine": async (wire, uniq) => {
    const definition = JSON.stringify({ Comment: "uic", StartAt: "Hello", States: { Hello: { Type: "Pass", Result: "World", End: true } } });
    await wire("POST", "/", {
      svc: "stepfunctions", target: "AWSStepFunctions.CreateStateMachine",
      body: { name: uniq, roleArn: "arn:aws:iam::123456789012:role/service-role/StepFunctions-vyomi-role", definition },
    });
    return uniq;
  },
};
