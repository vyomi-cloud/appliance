/* UI-conformance fixtures for Step Functions (native X-Amz-Target JSON). See s3/fixtures.mjs. */
const SFN = (op) => ({ svc: "states", target: `AWSStepFunctions.${op}` });
const ROLE_ARN = "arn:aws:iam::123456789012:role/service-role/StepFunctions-vyomi-role";
const DEFAULT_DEFINITION = JSON.stringify({ StartAt: "Pass", States: { Pass: { Type: "Pass", End: true } } });
const smArn = (name) => `arn:aws:states:us-east-1:000000000000:stateMachine:${name}`;

const ensureSm = (wire, name) => wire("POST", "/", { ...SFN("CreateStateMachine"), body: { name, roleArn: ROLE_ARN, definition: DEFAULT_DEFINITION } }).catch(() => {});

export default {
  "sm-fixture": async (wire) => { await ensureSm(wire, "uic-sm"); return "uic-sm"; },
  "live-sm": async (wire, uniq) => { await ensureSm(wire, uniq); return uniq; },
  "live-execution": async (wire, uniq) => {
    await ensureSm(wire, "uic-sm");
    await wire("POST", "/", { ...SFN("StartExecution"), body: { stateMachineArn: smArn("uic-sm"), name: uniq, input: "{}" } });
    return uniq;
  },
  "live-activity": async (wire, uniq) => { await wire("POST", "/", { ...SFN("CreateActivity"), body: { name: uniq } }); return uniq; },
};
