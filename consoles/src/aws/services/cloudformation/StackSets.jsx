/* StackSets with AWS Organizations trusted access (core/cloudformation_stacksets_core.py, sweep AWS-13): service-managed
 * permissions, OU-targeted stack instances and operations are real control-plane state; no stack is deployed into a member
 * account (aws.cloudformation.stacksets limitation). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import Select from "@cloudscape-design/components/select";
import Checkbox from "@cloudscape-design/components/checkbox";
import Multiselect from "@cloudscape-design/components/multiselect";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { ErrorAlert } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

function CreateStackSetModal({ visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("");
  const [model, setModel] = useState("SELF_MANAGED");
  const [auto, setAuto] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await api.createStackSet({ name, templateBody: template, permissionModel: model, autoDeployment: model === "SERVICE_MANAGED" && auto }); notify.success(`StackSet "${name}" created.`); onDone(); onDismiss(); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create stack set" size="large"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!name || !template} onClick={submit}>Create stack set</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Stack set name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Stack set name" /></FormField>
        <FormField label="Permission model" description="Service-managed permissions deploy to AWS Organizations accounts and need trusted access (below).">
          <Select ariaLabel="Permission model" selectedOption={{ value: model, label: model === "SERVICE_MANAGED" ? "Service-managed permissions" : "Self-service permissions" }}
            options={[{ value: "SELF_MANAGED", label: "Self-service permissions" }, { value: "SERVICE_MANAGED", label: "Service-managed permissions" }]}
            onChange={({ detail }) => setModel(detail.selectedOption.value)} />
        </FormField>
        {model === "SERVICE_MANAGED" && <Checkbox checked={auto} onChange={({ detail }) => setAuto(detail.checked)}>Enable automatic deployment to accounts added to the target OUs</Checkbox>}
        <FormField label="Template"><Textarea rows={10} value={template} onChange={({ detail }) => setTemplate(detail.value)} spellcheck={false} ariaLabel="Template" /></FormField>
      </SpaceBetween>
    </Modal>
  );
}

function TrustedAccess() {
  const notify = useNotify();
  const st = useAsync(() => api.orgsAccessStatus(), []);
  const [busy, setBusy] = useState(false);
  const on = st.data === "ENABLED";
  const toggle = async () => {
    setBusy(true);
    try { await (on ? api.deactivateOrgsAccess() : api.activateOrgsAccess()); notify.success(on ? "Trusted access disabled." : "Trusted access with AWS Organizations enabled."); st.reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Container header={<Header variant="h2" description="Lets CloudFormation StackSets deploy to the accounts of your AWS organization using service-managed permissions." actions={<Button loading={busy} onClick={toggle}>{on ? "Disable trusted access" : "Enable trusted access"}</Button>}>Trusted access</Header>}>
      {st.error ? <ErrorAlert error={st.error} /> : <StatusIndicator type={on ? "success" : "stopped"}>{st.data === undefined ? "Loading..." : on ? "Trusted access with AWS Organizations is enabled" : "Trusted access with AWS Organizations is disabled"}</StatusIndicator>}
    </Container>
  );
}

function InstancesModal({ stackSet, onDismiss }) {
  const notify = useNotify();
  const inst = useAsync(() => (stackSet ? api.listStackInstances(stackSet.StackSetName) : Promise.resolve([])), [stackSet?.StackSetName]);
  const ops = useAsync(() => (stackSet ? api.listStackSetOperations(stackSet.StackSetName) : Promise.resolve([])), [stackSet?.StackSetName]);
  const ous = useAsync(() => (stackSet ? api.listOrgUnits().catch(() => []) : Promise.resolve([])), [stackSet?.StackSetName]);
  const [regions, setRegions] = useState("us-east-1");
  const [accounts, setAccounts] = useState("");
  const [ouSel, setOuSel] = useState([]);
  const [busy, setBusy] = useState("");
  const managed = stackSet?.PermissionModel === "SERVICE_MANAGED";
  const run = async (kind) => {
    setBusy(kind);
    try {
      const args = { name: stackSet.StackSetName, regions: regions.split(/[,\s]+/).filter(Boolean), ouIds: ouSel.map((o) => o.value), accounts: accounts.split(/[,\s]+/).filter(Boolean) };
      await (kind === "add" ? api.createStackInstances(args) : api.deleteStackInstances(args));
      notify.success(kind === "add" ? "Stack instances deployed." : "Stack instances deleted."); inst.reload(); ops.reload();
    } catch (e) { notify.error(e); } finally { setBusy(""); }
  };
  return (
    <Modal visible={!!stackSet} size="large" onDismiss={onDismiss} header={`Stack instances: ${stackSet?.StackSetName || ""}`}
      footer={<Box float="right"><Button variant="primary" onClick={onDismiss}>Close</Button></Box>}>
      <SpaceBetween size="l">
        <SpaceBetween size="s">
          {managed && <FormField label="Organizational units"><Multiselect ariaLabel="Organizational units" selectedOptions={ouSel} onChange={({ detail }) => setOuSel(detail.selectedOptions)} placeholder="Choose OUs"
            options={(ous.data || []).map((o) => ({ value: o.id, label: o.name, description: o.id }))} /></FormField>}
          <FormField label={managed ? "Additional account IDs (optional)" : "Account IDs"}><Input ariaLabel="Account IDs" value={accounts} onChange={({ detail }) => setAccounts(detail.value)} placeholder="111122223333, ..." /></FormField>
          <FormField label="Regions"><Input ariaLabel="Regions" value={regions} onChange={({ detail }) => setRegions(detail.value)} /></FormField>
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="primary" loading={busy === "add"} onClick={() => run("add")}>Deploy stack instances</Button>
            <Button loading={busy === "del"} onClick={() => run("del")}>Delete stack instances</Button>
          </SpaceBetween>
        </SpaceBetween>
        <Table variant="embedded" header={<Header variant="h3" counter={`(${(inst.data || []).length})`}>Stack instances</Header>} items={inst.data || []} trackBy="StackId"
          columnDefinitions={[{ id: "a", header: "Account", cell: (i) => i.Account, isRowHeader: true }, { id: "r", header: "Region", cell: (i) => i.Region },
            { id: "ou", header: "Organizational unit", cell: (i) => i.OrganizationalUnitId || "-" }, { id: "s", header: "Status", cell: (i) => <StatusIndicator type="success">{i.Status}</StatusIndicator> }]}
          empty="No stack instances" />
        <Table variant="embedded" header={<Header variant="h3" counter={`(${(ops.data || []).length})`}>Operations</Header>} items={ops.data || []} trackBy="OperationId"
          columnDefinitions={[{ id: "id", header: "Operation ID", cell: (o) => o.OperationId, isRowHeader: true }, { id: "a", header: "Action", cell: (o) => o.Action }, { id: "s", header: "Status", cell: (o) => o.Status }]}
          empty="No operations" />
      </SpaceBetween>
    </Modal>
  );
}

export default function StackSets() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [inst, setInst] = useState(null);
  const { data = [], loading, error, reload } = useAsync(() => api.listStackSets(), []);

  return (
    <SpaceBetween size="l">
      <ResourceTable
        resourceName="StackSets"
        items={data}
        trackBy="StackSetId"
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find stack sets"
        columns={[
          { id: "n", header: "Stack set name", isRowHeader: true, cell: (s) => s.StackSetName },
          { id: "id", header: "Stack set ID", cell: (s) => s.StackSetId },
          { id: "pm", header: "Permission model", cell: (s) => s.PermissionModel },
          { id: "d", header: "Stack set description", cell: (s) => s.Description || "-" },
          { id: "drift", header: "Drift status", cell: () => "NOT_CHECKED" },
          { id: "dt", header: "Last drift check time", cell: () => "-" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={sel.length !== 1} items={[{ id: "instances", text: "Manage stack instances" }, { id: "delete", text: "Delete stack set" }]}
              onItemClick={async ({ detail }) => {
                if (detail.id === "instances") setInst(sel[0]);
                if (detail.id === "delete") {
                  try { await api.deleteStackSet(sel[0].StackSetName); notify.success(`StackSet "${sel[0].StackSetName}" deleted.`); setSel([]); reload(); }
                  catch (e) { notify.error(e); }
                }
              }}>Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => setCreate(true)}>Create stack set</Button>
          </SpaceBetween>
        }
        empty={{ title: "No stack sets to display", subtitle: "Create a stack set to get started.", action: <Button onClick={() => setCreate(true)}>Create stack set</Button> }}
      />
      <TrustedAccess />
      <InstancesModal stackSet={inst} onDismiss={() => setInst(null)} />
      <CreateStackSetModal visible={create} onDismiss={() => setCreate(false)} onDone={reload} />
    </SpaceBetween>
  );
}
