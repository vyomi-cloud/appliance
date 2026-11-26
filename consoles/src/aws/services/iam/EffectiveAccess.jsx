/* Effective access: principal + action + resource -> POST /api/iam/aws/evaluate -> allowed/denied, reason, matched statements.
 * The enforcement-aware sibling of the Policy simulator (which runs SimulatePrincipalPolicy). */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { PermissionPicker, PrincipalPicker, ResourceArnPicker } from "../../kit/PermissionPicker.jsx";
import { reasonText } from "../../../common/iamEnforce.js";
import { useIamApi } from "../../../common/iamEnforceHooks.js";

export default function EffectiveAccess() {
  const api = useIamApi("aws");
  const [principal, setPrincipal] = useState("");
  const [service, setService] = useState(null);
  const [name, setName] = useState("");
  const action = service && name ? `${service}:${name}` : "";
  const [resource, setResource] = useState("*");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await api.evaluate({ principal: { arn: principal }, action: action.trim(), resource: resource.trim() || "*" })); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <ContentLayout header={<Header variant="h1" description="Evaluate whether a principal may perform an action on a resource, using the same engine that enforces requests.">Effective access</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2" actions={<Button variant="primary" loading={busy} disabled={!principal || !action} onClick={run}>Evaluate</Button>}>Request</Header>}>
          <SpaceBetween size="m">
            <FormField label="Principal" description="A user or role in this account"><PrincipalPicker value={principal} onChange={setPrincipal} ariaLabel="Principal" /></FormField>
            <PermissionPicker service={service} action={name} onChange={({ service: sv, action: a }) => { setService(sv); setName(a); }} actionDescription="Verbatim IAM action from the service reference" />
            <FormField label="Resource ARN" description="Choose a resource type to prefill the ARN format"><ResourceArnPicker service={service} action={name} value={resource} onChange={setResource} /></FormField>
          </SpaceBetween>
        </Container>
        {err && <Alert type="error" header="Evaluation failed">{err.message}</Alert>}
        {res && (
          <Container header={<Header variant="h2">Result</Header>} data-testid="iam-eval-result">
            <SpaceBetween size="m">
              <StatusIndicator type={res.allowed ? "success" : "error"}>{res.allowed ? "Allowed" : "Denied"}</StatusIndicator>
              <Box>{reasonText(res)}</Box>
              <Table variant="embedded" header={<Header variant="h3" counter={`(${(res.matched || []).length})`}>Matched statements</Header>} items={res.matched || []}
                columnDefinitions={[
                  { id: "src", header: "Source", cell: (m) => m.source },
                  { id: "id", header: "Policy", cell: (m) => m.id },
                  { id: "eff", header: "Effect", cell: (m) => <StatusIndicator type={m.effect === "Deny" ? "error" : "success"}>{m.effect}</StatusIndicator> },
                  { id: "st", header: "Statement", cell: (m) => <Box variant="code">{JSON.stringify(m.statement || {})}</Box> },
                ]}
                empty={<Box color="inherit">No statement matched (implicit deny).</Box>} />
            </SpaceBetween>
          </Container>
        )}
      </SpaceBetween>
    </ContentLayout>
  );
}
