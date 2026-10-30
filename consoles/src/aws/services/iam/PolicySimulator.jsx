/* Policy simulator — real SimulatePrincipalPolicy. Principal picker (user or role),
 * editable action/resource lists, results table colored by EvalDecision. Global request
 * conditions aren't wired through (we don't fake a context builder we don't use). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
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
import { NotSimulated } from "../../kit/common.jsx";
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
    try { setResults(await api.simulatePrincipalPolicy(principal.value, actions, resources)); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => { setActions([]); setResources(["*"]); setResults(null); }}>Clear conditions</Button>
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
          <NotSimulated feature="Global request conditions" note="Per-request condition keys (aws:SourceIp, aws:MultiFactorAuthPresent, etc.) aren't wired into the simulator; only the action/resource pair is evaluated." />
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
              items={(results || []).map((r, i) => ({ id: i, service: (r.EvalActionName || "").split(":")[0], action: r.EvalActionName, resourceType: "-", resource: r.EvalResourceName, conditions: "-", result: r.EvalDecision }))}
              columnDefinitions={[
                { id: "service", header: "Service", cell: (r) => r.service },
                { id: "action", header: "Action", cell: (r) => r.action },
                { id: "rtype", header: "Resource type", cell: (r) => r.resourceType },
                { id: "resource", header: "Resource", cell: (r) => r.resource },
                { id: "cond", header: "Conditions", cell: (r) => r.conditions },
                { id: "result", header: "Result", cell: (r) => <StatusIndicator type={decisionType(r.result)}>{r.result}</StatusIndicator> },
                { id: "details", header: "Result details", cell: (r) => (r.result === "allowed" ? "Allowed by policy" : "Denied by policy") },
              ]}
              empty={<Box textAlign="center" color="inherit"><b>Add an identity to start</b><Box variant="p" color="inherit">Add actions above, choose a principal, then Simulate.</Box></Box>} />
          </SpaceBetween>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
