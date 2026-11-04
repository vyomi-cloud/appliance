/* UI-conformance fixtures for Systems Manager (native AmazonSSM.* JSON). See s3/fixtures.mjs. */
const T = (op) => ({ svc: "ssm", target: `AmazonSSM.${op}` });

export default {
  "live-parameter": async (wire, uniq) => {
    const name = `/vyomi/live/${uniq}`;
    await wire("POST", "/", { ...T("PutParameter"), body: { Name: name, Value: `v4 live ${uniq}`, Type: "String" } });
    return name;
  },
  "live-document": async (wire, uniq) => {
    const name = `vyomi-live-${uniq}`;
    await wire("POST", "/", { ...T("CreateDocument"), body: {
      Name: name, DocumentType: "Command", DocumentFormat: "JSON",
      Content: JSON.stringify({ schemaVersion: "2.2", description: `v4 live ${uniq}`, mainSteps: [] }),
    } });
    return name;
  },
  "live-command": async (wire, uniq) => {
    const r = await wire("POST", "/", { ...T("SendCommand"), body: {
      DocumentName: "AWS-RunShellScript", InstanceIds: ["i-0123456789abcdef0"], Comment: `v4 live ${uniq}`,
      Parameters: { commands: ["echo hi"] },
    } });
    return r.Command.CommandId;
  },
  "live-association": async (wire, uniq) => {
    const r = await wire("POST", "/", { ...T("CreateAssociation"), body: {
      Name: "AWS-UpdateSSMAgent", AssociationName: `v4-live-${uniq}`, Targets: [{ Key: "InstanceIds", Values: ["i-0123456789abcdef0"] }],
    } });
    return r.AssociationDescription.AssociationId;
  },
  "live-maintenance-window": async (wire, uniq) => {
    const r = await wire("POST", "/", { ...T("CreateMaintenanceWindow"), body: {
      Name: `vyomi-live-${uniq}`, Schedule: "rate(1 day)", Duration: 2, Cutoff: 0, AllowUnassociatedTargets: true,
    } });
    return r.WindowId;
  },
  "live-patch-baseline": async (wire, uniq) => {
    const r = await wire("POST", "/", { ...T("CreatePatchBaseline"), body: { Name: `vyomi-live-${uniq}`, OperatingSystem: "AMAZON_LINUX_2" } });
    return r.BaselineId;
  },
};
