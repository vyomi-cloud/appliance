/* Policy simulator — real SimulatePrincipalPolicy. Principal picker (user or role),
 * editable action/resource lists, arbitrary condition keys (sent as ContextEntries), an optional
 * resource policy, results table colored by EvalDecision with MissingContextValues surfaced. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Table from "@cloudscape-design/components/table";
import Select from "@cloudscape-design/components/select";
import Input from "@cloudscape-design/components/input";
import FormField from "@cloudscape-design/components/form-field";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import Textarea from "@cloudscape-design/components/textarea";
import { asList } from "../../../common/wire.js";
import * as api from "./api.js";

const decisionType = (d) => (d === "allowed" ? "success" : "error");

export default function PolicySimulator() {
  const notify = useNotify();
  const data = useAsync(() => Promise.all([api.listUsers(), api.listRoles()]), []);
  const [principal, setPrincipal] = useState(null);
  const [actions, setActions] = useState([]);
  const [newAction, setNewAction] = useState("");
  const [resources, setResources] = useState(["*"]);
  const [newResource, setNewResource] = useState("");
  const [mfaPresent, setMfaPresent] = useState(false);
  const [ctxKey, setCtxKey] = useState("");
  const [ctxVal, setCtxVal] = useState("");
  const [ctx, setCtx] = useState({});
  const [resourcePolicy, setResourcePolicy] = useState("");
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);

  if (data.loading) return <Box padding="l">Loading…</Box>;
  const [users, roles] = data.data;
  const options = [
    ...users.map((u) => ({ value: u.Arn, label: `User: ${u.UserName}` })),
    ...roles.map((r) => ({ value: r.Arn, label: `Role: ${r.RoleName}` })),
  ];

  const simulate = async () => {
    setBusy(true);
    try {
      const contextEntries = [{ key: "aws:MultiFactorAuthPresent", value: mfaPresent ? "true" : "false" },
        ...Object.entries(ctx).map(([key, value]) => ({ key, value }))];
      const evaluations = await api.simulatePrincipalPolicy(principal.value, actions, resources, contextEntries, resourcePolicy);
      setResults(evaluations.map((r) => ({ ...r, _cond: contextEntries.map((e) => `${e.key}=${e.value}`).join(", "), _missing: asList(r.MissingContextValues?.member) })));
    }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => { setActions([]); setResources(["*"]); setMfaPresent(false); setResults(null); }}>Clear conditions</Button>
        <Button variant="primary" disabled={!principal || !actions.length} loading={busy} onClick={simulate}>Simulate</Button>
      </SpaceBetween>
    }>Policy simulator</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Principal</Header>}>
          <SpaceBetween size="m">
            <FormField label="Principal">
              <Select selectedOption={principal} onChange={({ detail }) => setPrincipal(detail.selectedOption)} options={options} placeholder="Choose a user or role" />
            </FormField>
            <FormField label="Identities" description="Select an identity to simulate">
              <Button disabled={!principal}>Add identity</Button>
            </FormField>
          </SpaceBetween>
        </Container>
        <ExpandableSection headerText="Global request conditions">
          <SpaceBetween size="m">
            <Checkbox checked={mfaPresent} onChange={({ detail }) => setMfaPresent(detail.checked)}>
              aws:MultiFactorAuthPresent
            </Checkbox>
            <SpaceBetween direction="horizontal" size="xs">
              <Input value={ctxKey} onChange={({ detail }) => setCtxKey(detail.value)} placeholder="Condition key, e.g. aws:SourceIp" ariaLabel="Condition key" />
              <Input value={ctxVal} onChange={({ detail }) => setCtxVal(detail.value)} placeholder="Value" ariaLabel="Condition value" />
              <Button disabled={!ctxKey} onClick={() => { setCtx({ ...ctx, [ctxKey]: ctxVal }); setCtxKey(""); setCtxVal(""); }}>Add condition key</Button>
            </SpaceBetween>
            {Object.entries(ctx).map(([k, v]) => (
              <SpaceBetween key={k} direction="horizontal" size="xs"><Box variant="code">{k} = {v}</Box>
                <Button variant="inline-link" onClick={() => { const { [k]: _, ...rest } = ctx; setCtx(rest); }}>Remove</Button></SpaceBetween>
            ))}
            <FormField label="Resource policy (optional)" description="A resource-based policy document evaluated together with the identity policies.">
              <Textarea rows={5} value={resourcePolicy} onChange={({ detail }) => setResourcePolicy(detail.value)} ariaLabel="Resource policy" spellcheck={false} />
            </FormField>
          </SpaceBetween>
        </ExpandableSection>
        <Container header={<Header variant="h2" counter={`(${(results || []).length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!actions.length} onClick={() => setActions([])}>Remove all</Button>
            <Button onClick={() => { if (newAction) { setActions([...actions, newAction]); setNewAction(""); } }}>Add actions</Button>
          </SpaceBetween>
        }>Simulation results</Header>}>
          <SpaceBetween size="m">
            <SpaceBetween direction="horizontal" size="xs">
              <Input value={newAction} onChange={({ detail }) => setNewAction(detail.value)} placeholder="e.g. s3:GetObject" ariaLabel="Action name" />
              <Input value={newResource} onChange={({ detail }) => setNewResource(detail.value)} placeholder="Resource ARN (default *)" ariaLabel="Resource ARN" />
              <Button onClick={() => { if (newResource) { setResources([...new Set([...resources, newResource])]); setNewResource(""); } }}>Add resource</Button>
            </SpaceBetween>
            <Table variant="embedded"
              items={(results || []).map((r, i) => ({ id: i, service: (r.EvalActionName || "").split(":")[0], action: r.EvalActionName, resourceType: "-", resource: r.EvalResourceName, conditions: r._cond, missing: r._missing, result: r.EvalDecision }))}
              columnDefinitions={[
                { id: "service", header: "Service", cell: (r) => r.service },
                { id: "action", header: "Action", cell: (r) => r.action },
                { id: "rtype", header: "Resource type", cell: (r) => r.resourceType },
                { id: "resource", header: "Resource", cell: (r) => r.resource },
                { id: "cond", header: "Conditions", cell: (r) => r.conditions },
                { id: "result", header: "Result", cell: (r) => <StatusIndicator type={decisionType(r.result)}>{r.result}</StatusIndicator> },
                { id: "details", header: "Result details", cell: (r) => (r.result === "allowed" ? "Allowed by policy" : "Denied by policy") + (r.missing?.length ? ` - missing context values: ${r.missing.join(", ")}` : "") },
              ]}
              empty={<Box textAlign="center" color="inherit"><b>Add an identity to start</b><Box variant="p" color="inherit">Add actions above, choose a principal, then Simulate.</Box></Box>} />
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
