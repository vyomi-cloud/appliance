/* Lambda > Configuration > Permissions > Resource-based policy statements: the REAL stored statements (GetPolicy) with Remove
 * (RemovePermission), and the console's "Add permissions" form (AddPermission) driven by the shared pickers (service principal / IAM
 * principal, lambda:* action from the verbatim catalog, source ARN, source account, org ID, Function URL auth type). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { ActionPicker, PrincipalPicker } from "../../kit/PermissionPicker.jsx";
import * as api from "./api.js";

const SERVICES = ["apigateway.amazonaws.com", "events.amazonaws.com", "s3.amazonaws.com", "sns.amazonaws.com", "sqs.amazonaws.com", "logs.amazonaws.com", "lex.amazonaws.com"];
const principalText = (p) => (p === "*" ? "*" : Object.values(p || {}).flat().join(", "));

export default function ResourcePermissions({ name, revision, onChanged }) {
  const notify = useNotify();
  const policy = useAsync(() => api.getPolicy(name), [name, revision]);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const open = () => { setErr(null); setForm({ kind: "service", sid: "", service: "", account: "", arn: "", action: "InvokeFunction", sourceArn: "", sourceAccount: "", org: "", urlAuth: "" }); };
  const set = (p) => setForm({ ...form, ...p });
  const principal = form && (form.kind === "service" ? form.service : form.kind === "iam" ? form.arn : form.account);
  const valid = form && form.sid.trim() && principal;
  const reload = () => { policy.reload(); onChanged && onChanged(); };
  const add = async () => {
    setBusy(true); setErr(null);
    try {
      await api.addPermission(name, {
        StatementId: form.sid.trim(), Action: `lambda:${form.action}`, Principal: principal,
        ...(form.sourceArn ? { SourceArn: form.sourceArn } : {}), ...(form.sourceAccount ? { SourceAccount: form.sourceAccount } : {}),
        ...(form.org ? { PrincipalOrgID: form.org } : {}), ...(form.urlAuth ? { FunctionUrlAuthType: form.urlAuth } : {}),
      });
      notify.success("The statement was added to the resource-based policy."); setForm(null); reload();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const remove = async (sid) => { try { await api.removePermission(name, sid); notify.success(`Statement ${sid} removed.`); reload(); } catch (e) { notify.error(e); } };
  return (
    <SpaceBetween size="m">
      <Table variant="container" header={<Header variant="h2" counter={`(${policy.data?.Statement?.length || 0})`} actions={<Button onClick={open}>Add permissions</Button>}>Resource-based policy statements</Header>}
        items={policy.data?.Statement || []} trackBy="Sid" loading={policy.loading}
        columnDefinitions={[
          { id: "sid", header: "Statement ID", cell: (s) => s.Sid },
          { id: "p", header: "Principal", cell: (s) => principalText(s.Principal) },
          { id: "org", header: "Principal organization ID", cell: (s) => s.Condition?.StringEquals?.["aws:PrincipalOrgID"] || "-" },
          { id: "cond", header: "Conditions", cell: (s) => (s.Condition ? JSON.stringify(s.Condition) : "-") },
          { id: "action", header: "Action", cell: (s) => [].concat(s.Action).join(", ") },
          { id: "rm", header: "", cell: (s) => <Button variant="inline-link" onClick={() => remove(s.Sid)} ariaLabel={`Delete statement ${s.Sid}`}>Delete</Button> },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No resource-based policy statements</b></Box>} />
      {form && (
        <Container header={<Header variant="h2" description="Grant another service or account permission to use this function.">Add permissions</Header>}>
          <SpaceBetween size="m">
            <ErrorAlert error={err} header="Couldn't add the statement" />
            <FormField label="Statement ID" constraintText="Unique within this policy."><Input ariaLabel="Statement ID" value={form.sid} onChange={({ detail }) => set({ sid: detail.value })} /></FormField>
            <FormField label="Principal type">
              <RadioGroup value={form.kind} onChange={({ detail }) => set({ kind: detail.value })} items={[
                { value: "service", label: "AWS service" }, { value: "account", label: "AWS account" }, { value: "iam", label: "IAM user or role" }]} />
            </FormField>
            {form.kind === "service" && <FormField label="Service principal"><Select ariaLabel="Service principal" placeholder="Choose a service" selectedOption={form.service ? { value: form.service, label: form.service } : null}
              options={SERVICES.map((s) => ({ value: s, label: s }))} onChange={({ detail }) => set({ service: detail.selectedOption.value })} /></FormField>}
            {form.kind === "account" && <FormField label="Account ID"><Input ariaLabel="Account ID" value={form.account} onChange={({ detail }) => set({ account: detail.value })} placeholder="123456789012" /></FormField>}
            {form.kind === "iam" && <FormField label="IAM principal"><PrincipalPicker value={form.arn} onChange={(arn) => set({ arn })} ariaLabel="IAM principal" /></FormField>}
            <FormField label="Action"><ActionPicker service="lambda" value={form.action} ariaLabel="Action" onChange={(action) => set({ action })} /></FormField>
            <ExpandableSection headerText="Conditions - optional" variant="footer">
              <SpaceBetween size="s">
                <FormField label="Source ARN"><Input ariaLabel="Source ARN" value={form.sourceArn} onChange={({ detail }) => set({ sourceArn: detail.value })} /></FormField>
                <FormField label="Source account"><Input ariaLabel="Source account" value={form.sourceAccount} onChange={({ detail }) => set({ sourceAccount: detail.value })} /></FormField>
                <FormField label="Principal organization ID"><Input ariaLabel="Principal organization ID" value={form.org} onChange={({ detail }) => set({ org: detail.value })} /></FormField>
                <FormField label="Function URL auth type"><Select ariaLabel="Function URL auth type" selectedOption={{ value: form.urlAuth, label: form.urlAuth || "None" }}
                  options={[{ value: "", label: "None" }, { value: "NONE", label: "NONE" }, { value: "AWS_IAM", label: "AWS_IAM" }]} onChange={({ detail }) => set({ urlAuth: detail.selectedOption.value })} /></FormField>
              </SpaceBetween>
            </ExpandableSection>
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="link" onClick={() => setForm(null)} disabled={busy}>Cancel</Button>
              <Button variant="primary" disabled={!valid} loading={busy} onClick={add}>Save</Button>
            </SpaceBetween>
          </SpaceBetween>
        </Container>
      )}
    </SpaceBetween>
  );
}
