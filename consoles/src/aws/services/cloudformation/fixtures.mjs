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

async function ensureHook(wire, typeName, { failureMode = "WARN", targetOperations = ["CREATE"], targetStacks = "ALL", requiredTags = [] } = {}) {
  await wire("POST", "/", Q("RegisterType", { Type: "HOOK", TypeName: typeName }));
  const configuration = JSON.stringify({
    CloudFormationConfiguration: { HookConfiguration: {
      FailureMode: failureMode, TargetOperations: targetOperations,
      TargetStacks: targetStacks === "ALL" ? "ALL" : targetStacks,
      Properties: { RequiredTagKeys: requiredTags.join(","), Enabled: "true" },
    } },
  });
  await wire("POST", "/", Q("SetTypeConfiguration", { TypeName: typeName, Configuration: configuration }));
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

  // Scans the account's real resources (an IAM role from a freshly created stack among
  // them) then generates a template from that role, so the Templates tab shows a real,
  // non-empty generated template — not a static list.
  "live-iac-generator": async (wire, uniq) => {
    const roleName = `${uniq}-role`;
    await wire("POST", "/", Q("CreateStack", {
      StackName: `${uniq}-stack`,
      "Capabilities.member.1": "CAPABILITY_NAMED_IAM",
      TemplateBody: JSON.stringify({ Resources: { R: { Type: "AWS::IAM::Role", Properties: { RoleName: roleName } } } }),
    }));
    await wire("POST", "/", Q("StartResourceScan", {}));
    await wire("POST", "/", Q("CreateGeneratedTemplate", {
      GeneratedTemplateName: uniq,
      "Resources.member.1.ResourceType": "AWS::IAM::Role",
      "Resources.member.1.ResourceIdentifier.entry.1.key": "RoleName",
      "Resources.member.1.ResourceIdentifier.entry.1.value": roleName,
    }));
    return uniq;
  },

  // Moves a resource from one freshly created stack into another via CreateStackRefactor +
  // ExecuteStackRefactor, so the Stack refactors list shows a real, non-empty refactor.
  "live-stack-refactor": async (wire, uniq) => {
    const src = `${uniq}-src`, dst = `${uniq}-dst`;
    await wire("POST", "/", Q("CreateStack", { StackName: src, TemplateBody: queueTemplate("Q") }));
    await wire("POST", "/", Q("CreateStack", { StackName: dst, TemplateBody: queueTemplate("Q2") }));
    const created = await wire("POST", "/", Q("CreateStackRefactor", {
      Description: uniq,
      "ResourceMappings.member.1.Source.StackName": src,
      "ResourceMappings.member.1.Source.LogicalResourceId": "Q",
      "ResourceMappings.member.1.Destination.StackName": dst,
      "ResourceMappings.member.1.Destination.LogicalResourceId": "QMoved",
    }));
    const id = /<StackRefactorId>(.*?)<\/StackRefactorId>/.exec(created)?.[1];
    if (id) await wire("POST", "/", Q("ExecuteStackRefactor", { StackRefactorId: id }));
    return uniq;
  },

  "cfn-hook": async (wire) => { await ensureHook(wire, "Vyomi::Fixture::UicHook"); return "Vyomi::Fixture::UicHook"; },
  "live-hook": async (wire, uniq) => { const name = `Vyomi::Fixture::${uniq}`; await ensureHook(wire, name); return name; },

  // A hook scoped to one specific stack generates a real PRE_PROVISION invocation when
  // that stack is created, so the Invocation summary page shows a non-empty, real row.
  "cfn-hook-invocation": async (wire) => {
    const stack = "uic-hook-invocation-stack";
    await ensureHook(wire, "Vyomi::Fixture::UicInvocationHook", { targetStacks: [stack] });
    await ensureStack(wire, stack);
    return stack;
  },
  "live-hook-invocation": async (wire, uniq) => {
    const stack = `${uniq}-stack`;
    await ensureHook(wire, `Vyomi::Fixture::${uniq}`, { targetStacks: [stack] });
    await ensureStack(wire, stack);
    return stack;
  },
};
