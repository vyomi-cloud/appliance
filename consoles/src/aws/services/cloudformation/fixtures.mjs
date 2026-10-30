/* UI-conformance fixtures for CloudFormation (native Query-protocol form POST). See
 * s3/fixtures.mjs and iam/fixtures.mjs for the harness contract: each export is async
 * (wire, uniq) → the unique resource name the page must then show. */
const Q = (Action, body) => ({
  svc: "cloudformation",
  body: new URLSearchParams({ Action, ...body }).toString(),
  headers: { "content-type": "application/x-www-form-urlencoded; charset=utf-8" },
});

const queueTemplate = (logicalId = "Q") => JSON.stringify({
  Resources: { [logicalId]: { Type: "AWS::SQS::Queue", Properties: {} } },
});

async function ensureStack(wire, name) {
  await wire("POST", "/", Q("CreateStack", { StackName: name, TemplateBody: queueTemplate() })).catch(() => {});
}

export default {
  "cfn-stack": async (wire) => { await ensureStack(wire, "uic-stack"); return "uic-stack"; },
  "live-stack": async (wire, uniq) => { await ensureStack(wire, uniq); return uniq; },

  "cfn-stackset": async (wire) => {
    await wire("POST", "/", Q("CreateStackSet", { StackSetName: "uic-stackset", TemplateBody: queueTemplate() })).catch(() => {});
    return "uic-stackset";
  },
  "live-stackset": async (wire, uniq) => {
    await wire("POST", "/", Q("CreateStackSet", { StackSetName: uniq, TemplateBody: queueTemplate() }));
    return uniq;
  },

  "cfn-export-stack": async (wire) => {
    const tpl = JSON.stringify({
      Resources: { Q: { Type: "AWS::SQS::Queue", Properties: {} } },
      Outputs: { QueueRef: { Value: { Ref: "Q" }, Export: { Name: "uic-export" } } },
    });
    await wire("POST", "/", Q("CreateStack", { StackName: "uic-export-stack", TemplateBody: tpl })).catch(() => {});
    return "uic-export";
  },
  "live-export": async (wire, uniq) => {
    const tpl = JSON.stringify({
      Resources: { Q: { Type: "AWS::SQS::Queue", Properties: {} } },
      Outputs: { QueueRef: { Value: { Ref: "Q" }, Export: { Name: uniq } } },
    });
    await wire("POST", "/", Q("CreateStack", { StackName: `${uniq}-stack`, TemplateBody: tpl }));
    return uniq;
  },
};
