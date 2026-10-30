import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Toggle from "@cloudscape-design/components/toggle";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, KeyValue, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { statusOf } from "./Stacks.jsx";
import * as api from "./api.js";

function Overview({ d, reload }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const toggleProtection = async () => {
    setBusy(true);
    try {
      await api.updateTerminationProtection(d.StackName, d.EnableTerminationProtection !== "true");
      notify.success(`Termination protection ${d.EnableTerminationProtection === "true" ? "disabled" : "enabled"}.`);
      reload();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <SpaceBetween size="l">
      <KeyValue title="Overview" actions={<Button loading={busy} onClick={toggleProtection}>{d.EnableTerminationProtection === "true" ? "Disable termination protection" : "Enable termination protection"}</Button>} columns={3} items={[
        ["Stack ID", d.StackId], ["Description", d.Description || "-"], ["Status", statusOf(d.StackStatus)],
        ["Detailed status", d.StackStatusReason ? "-" : "-"], ["Status reason", d.StackStatusReason || "-"], ["Root stack", "-"],
        ["Parent stack", "-"], ["Created time", fmtDate(d.CreationTime)], ["Deleted time", fmtDate(d.DeletionTime)],
        ["Updated time", fmtDate(d.LastUpdatedTime)], ["Drift status", d.DriftInformation?.StackDriftStatus || "NOT_CHECKED"],
        ["Last drift check time", fmtDate(d.DriftInformation?.LastCheckTimestamp)], ["Termination protection", d.EnableTerminationProtection === "true" ? "Activated" : "Deactivated"],
        ["IAM role", d.RoleARN || "-"],
      ]} />
      <Table variant="container" header={<Header variant="h2" counter={`(${Object.keys(d.Tags || {}).length})`}>Tags</Header>}
        items={Object.entries(d.Tags || {}).map(([k, v]) => ({ k, v }))}
        columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.k }, { id: "v", header: "Value", cell: (x) => x.v }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      <NotSimulatedContainer title="Stack policy" note="Stack policies (protecting resources from accidental updates) are stored on CreateStack's StackPolicyBody but not enforced by Vyomi." />
      <NotSimulatedContainer title="Rollback configuration" note="CloudWatch alarm-triggered rollback monitoring isn't modeled; rollback on provisioning failure still works." />
      <NotSimulatedContainer title="Notification options" note="SNS notification ARNs for stack events are stored but Vyomi doesn't publish to them." />
    </SpaceBetween>
  );
}

function Events({ name }) {
  const { data = [], loading, reload } = useAsync(() => api.describeStackEvents(name), [name]);
  return (
    <Table variant="container" loading={loading} items={data} trackBy="EventId"
      header={<Header variant="h2" counter={`(${data.length})`} actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={reload} />}>Events</Header>}
      columnDefinitions={[
        { id: "ts", header: "Timestamp", cell: (e) => fmtDate(e.Timestamp) },
        { id: "lid", header: "Logical ID", cell: (e) => e.LogicalResourceId },
        { id: "status", header: "Status", cell: (e) => statusOf(e.ResourceStatus) },
        { id: "dstatus", header: "Detailed status", cell: () => "-" },
        { id: "reason", header: "Status reason", cell: (e) => e.ResourceStatusReason || "-" },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No events</b></Box>} />
  );
}

function Resources({ name }) {
  const { data = [], loading, reload } = useAsync(() => api.describeStackResources(name), [name]);
  return (
    <Table variant="container" loading={loading} items={data} trackBy="LogicalResourceId"
      header={<Header variant="h2" counter={`(${data.length})`} actions={<Button iconName="refresh" ariaLabel="Refresh" onClick={reload} />}>Resources</Header>}
      columnDefinitions={[
        { id: "lid", header: "Logical ID", cell: (r) => r.LogicalResourceId },
        { id: "pid", header: "Physical ID", cell: (r) => r.PhysicalResourceId },
        { id: "type", header: "Type", cell: (r) => r.ResourceType },
        { id: "status", header: "Status", cell: (r) => statusOf(r.ResourceStatus) },
        { id: "module", header: "Module", cell: () => "-" },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No resources</b></Box>} />
  );
}

function Outputs({ d }) {
  const rows = d.Outputs || [];
  return (
    <Table variant="container" items={rows} trackBy="OutputKey"
      header={<Header variant="h2" counter={`(${rows.length})`}>Outputs</Header>}
      columnDefinitions={[
        { id: "k", header: "Key", cell: (o) => o.OutputKey },
        { id: "v", header: "Value", cell: (o) => o.OutputValue },
        { id: "d", header: "Description", cell: (o) => o.Description || "-" },
        { id: "e", header: "Export name", cell: (o) => o.ExportName || "-" },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No outputs</b></Box>} />
  );
}

function Parameters({ d }) {
  const rows = Object.entries(d.Parameters || {}).map(([k, v]) => ({ k, v }));
  return (
    <Table variant="container" items={rows} trackBy="k"
      header={<Header variant="h2" counter={`(${rows.length})`}>Parameters</Header>}
      columnDefinitions={[
        { id: "k", header: "Key", cell: (p) => p.k }, { id: "v", header: "Value", cell: (p) => p.v },
        { id: "r", header: "Resolved value", cell: (p) => p.v },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No parameters</b></Box>} />
  );
}

function TemplateTab({ name }) {
  const [processed, setProcessed] = useState(false);
  const { data = "", loading } = useAsync(() => api.getTemplate(name), [name]);
  return (
    <SpaceBetween size="l">
      <Header variant="h2" actions={<SpaceBetween direction="horizontal" size="xs"><Button onClick={() => navigator.clipboard?.writeText(data)}>Copy</Button><Button disabled>View in Application Composer</Button></SpaceBetween>}>Template</Header>
      <Toggle checked={processed} onChange={({ detail }) => setProcessed(detail.checked)}>View processed template</Toggle>
      {loading ? <Spinner /> : <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{data}</pre></Box>}
    </SpaceBetween>
  );
}

function CreateChangeSetModal({ name, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [csName, setCsName] = useState(`${name}-changeset`);
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createChangeSet({ stackName: name, changeSetName: csName, templateBody: template });
      notify.success(`Change set "${csName}" created.`); onDone(); onDismiss();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create change set" size="large"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onDismiss}>Cancel</Button><Button variant="primary" loading={busy} disabled={!csName || !template} onClick={submit}>Create change set</Button></SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Change set name"><Input value={csName} onChange={({ detail }) => setCsName(detail.value)} ariaLabel="Change set name" /></FormField>
        <FormField label="Template" description="The updated template (JSON or YAML) to diff against the current stack.">
          <Textarea rows={12} value={template} onChange={({ detail }) => setTemplate(detail.value)} spellcheck={false} ariaLabel="Template" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function ChangeSets({ name }) {
  const notify = useNotify();
  const { data = [], loading, reload } = useAsync(() => api.listChangeSets(name), [name]);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const execute = async (cs) => {
    try { await api.executeChangeSet(cs.ChangeSetName, name); notify.success(`Executing change set "${cs.ChangeSetName}".`); reload(); }
    catch (e) { notify.error(e); }
  };
  return (
    <>
      <Table variant="container" loading={loading} items={data} trackBy="ChangeSetId" selectionType="single" selectedItems={sel}
        onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
        header={<Header variant="h2" counter={`(${data.length})`} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button disabled={sel.length !== 1 || sel[0].ExecutionStatus !== "AVAILABLE"} onClick={() => execute(sel[0])}>Execute</Button>
            <Button variant="primary" onClick={() => setCreate(true)}>Create change set</Button>
          </SpaceBetween>
        }>Change sets</Header>}
        columnDefinitions={[
          { id: "n", header: "Change set name", isRowHeader: true, cell: (c) => c.ChangeSetName },
          { id: "c", header: "Created time", cell: (c) => fmtDate(c.CreationTime) },
          { id: "s", header: "Status", cell: (c) => statusOf(c.Status) },
          { id: "e", header: "Execution status", cell: (c) => c.ExecutionStatus },
          { id: "d", header: "Description", cell: (c) => c.Description || "-" },
        ]}
        empty={<Box textAlign="center" color="inherit"><b>No change sets</b></Box>} />
      <CreateChangeSetModal name={name} visible={create} onDismiss={() => setCreate(false)} onDone={reload} />
      <DeleteModal visible={del} resourceType="change set" names={sel.map((c) => c.ChangeSetName)} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteChangeSet(sel[0].ChangeSetName, name); notify.success(`Change set "${sel[0].ChangeSetName}" deleted.`); setSel([]); reload(); }} />
    </>
  );
}

export default function StackDetail({ params, query }) {
  const name = params.name;
  const [tab, setTab] = useState(query.tab || "info");
  const [del, setDel] = useState(false);
  const notify = useNotify();
  const t = useAsync(() => api.describeStack(name), [name]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const d = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={t.reload} iconName="refresh" ariaLabel="Refresh" />
        <Button disabled={d.EnableTerminationProtection === "true"} onClick={() => setDel(true)}>Delete</Button>
        <Button onClick={() => navigate("cloudformation", "stacks", name, "update")}>Update stack</Button>
        <ButtonDropdown items={[{ id: "changeset", text: "Create change set" }, { id: "rollback", text: "Continue update rollback" }]}
          onItemClick={async ({ detail }) => {
            try {
              if (detail.id === "changeset") setTab("changesets");
              if (detail.id === "rollback") { await api.continueUpdateRollback(name); notify.success("Continuing rollback."); t.reload(); }
            } catch (e) { notify.error(e); }
          }}>Stack actions</ButtonDropdown>
        <Button variant="primary" href={`#/cloudformation/create`}>Create stack</Button>
      </SpaceBetween>
    }>{name}</Header>}>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "info", label: "Stack info", content: <Overview d={d} reload={t.reload} /> },
        { id: "events", label: "Events", content: <Events name={name} /> },
        { id: "resources", label: "Resources", content: <Resources name={name} /> },
        { id: "outputs", label: "Outputs", content: <Outputs d={d} /> },
        { id: "parameters", label: "Parameters", content: <Parameters d={d} /> },
        { id: "template", label: "Template", content: <TemplateTab name={name} /> },
        { id: "changesets", label: "Change sets", content: <ChangeSets name={name} /> },
        { id: "gitsync", label: "Git sync", content: <NotSimulatedContainer title="Git sync" note="Syncing a stack to a Git repository isn't modeled by Vyomi." /> },
      ]} />
      <DeleteModal visible={del} resourceType="stack" names={[name]} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteStack(name); notify.success(`Deletion of stack "${name}" has been initiated.`); navigate("cloudformation", "stacks"); }} />
    </ContentLayout>
  );
}
